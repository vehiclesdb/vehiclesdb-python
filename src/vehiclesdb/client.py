"""The VehiclesDB client: dataset mode by default, API mode when a key is set.

Read `CONTRACT.md` (the parity contract) before changing anything in here.
The short version: the canonical id `kind/make_slug/model_slug` is the product,
this package exists so a stranger's codebase ends up storing it, and the Ruby /
JS / Python clients must give the same answer to the same question.

Two hard rules this file obeys:

1. **No unshipped endpoints.** `images()` (`GET /api/v1/vehicles/.../images`)
   is the one API call. Everything else is answered locally from the
   published CC-BY dataset. There is no method here for `stats`, `markets`, `plates`, `vin` or
   `resolve/batch` — a method that 404s invites integrations onto semantics we
   have not shipped.
2. **Nothing fetches in `__init__`.** Constructing a client is free; the
   dataset is fetched once on first use and memoized, and the heavier per-kind
   catalog only when a full record is asked for.
"""

import json
import socket
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from ._normalize import fold
from .errors import (
    DatasetError,
    MissingApiKeyError,
    TransportError,
    VehiclesDBApiError,
    VehiclesDBError,
    VehiclesDBTimeoutError,
    api_error,
)
from ._labels import BODY_TYPE_LABELS, COLOR_SYNONYMS, COLORS, KIND_LABELS, locale_of
from .models import Make, Model, Resolution

# Keep in sync with `version` in pyproject.toml (there is no build-time
# metadata read here on purpose: this package must import with zero deps and
# without being installed, which is how the offline tests run it).
__version__ = "0.2.0"

# The exact CDN base the published Ruby gem uses, minus the trailing path —
# vehicles/lib/vehicles/configuration.rb:72 sets
#   @data_url = "https://cdn.jsdelivr.net/gh/vehiclesdb/vehiclesdb@latest/dist/vehicles.json"
# Same host, same repo, same @version pin, so all three SDKs are demonstrably
# reading the same bytes. `@latest` follows the newest git tag; pin a release
# (`version="2026.07.6"`) when you want reproducible answers.
DATASET_BASE_URL_TEMPLATE = "https://cdn.jsdelivr.net/gh/vehiclesdb/vehiclesdb@{version}"

DEFAULT_API_BASE_URL = "https://vehiclesdb.com"

# CC-BY 4.0 §3(a) makes visible credit a LICENCE CONDITION, not a courtesy.
# The wording is copied from the data repo's README ("License & attribution
# (required)") — do not paraphrase a licence statement. Upstream register
# notices (KBA `dl-de/by-2-0`, RDW, Traficom, ...) apply under every licence
# including the commercial one, so we point at ATTRIBUTION.md rather than
# summarise terms that are not ours to restate.
ATTRIBUTION_TEXT = (
    "Vehicle data by VehiclesDB (https://vehiclesdb.com), licensed under "
    "CC-BY 4.0 (https://creativecommons.org/licenses/by/4.0/). "
    "Upstream register notices: "
    "https://github.com/vehiclesdb/vehiclesdb/blob/main/ATTRIBUTION.md"
)
ATTRIBUTION_HTML = (
    '<a href="https://vehiclesdb.com">Vehicle data by VehiclesDB</a>'
)

# Deciles run 1 (most popular) .. 10, and SCHEMA.md says the key is absent when
# a model is unranked. 99 sorts every unranked model behind every ranked one
# without special-casing None in half a dozen sort keys.
_UNRANKED = 99

# RESOLUTION.md §3a: when one nameplate answers in several kinds and the caller
# gave no kind, the tie-break is lowest mass_decile, then this kind
# precedence, then the id. Identical on every VehiclesDB surface.
KIND_PRECEDENCE = ("van", "car", "bus", "truck", "moped", "motorcycle")

Transport = Callable[[str, Dict[str, str]], Tuple[int, bytes]]


# --------------------------------------------------------------------------
# transports
# --------------------------------------------------------------------------

def urllib_transport(timeout: float = 10.0) -> Transport:
    """The zero-dependency default: `urllib.request`, stdlib only.

    A transport is `transport(url: str, headers: Dict[str, str]) -> (status, bytes)`.
    It returns the status instead of raising for 4xx/5xx, because the API's
    error bodies are documented JSON that callers need to see
    (`{"error": "no_image", "id": ...}`); only a failure to get any response at
    all is an exception. That one signature is the whole seam the tests use to
    stay offline.
    """

    def _fetch(url: str, headers: Dict[str, str]) -> Tuple[int, bytes]:
        request = urllib.request.Request(url, headers=headers, method="GET")
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.getcode(), response.read()
        except urllib.error.HTTPError as exc:
            # An HTTPError IS a response object. Reading it here is what lets
            # a 404 surface as VehiclesDBApiError(404, {"error": "no_image"})
            # instead of an opaque stdlib exception.
            return exc.code, exc.read()
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, socket.timeout):
                raise VehiclesDBTimeoutError(url, exc)
            raise TransportError(url, exc)
        except socket.timeout as exc:  # TimeoutError on 3.10+
            raise VehiclesDBTimeoutError(url, exc)
        except OSError as exc:  # connection resets
            raise TransportError(url, exc)

    return _fetch


def httpx_transport(client: Any = None, timeout: float = 10.0) -> Transport:
    """Optional transport backed by httpx (`pip install "vehiclesdb[httpx]"`).

    httpx is imported INSIDE the returned callable, never at module import
    time, so the package keeps its "zero required dependencies" promise and
    `import vehiclesdb` works on a machine that has never heard of httpx.

    Pass your own `httpx.Client` to reuse connections and inherit your app's
    proxy/retry/limits config; pass nothing and a client is created and closed
    per request, which is fine for the one-or-two calls a dataset-mode client
    makes but wasteful in a hot loop.
    """

    def _fetch(url: str, headers: Dict[str, str]) -> Tuple[int, bytes]:
        try:
            if client is not None:
                response = client.get(url, headers=headers)
                return response.status_code, response.content
            import httpx  # noqa: F401  (deliberately lazy — see docstring)

            with httpx.Client(timeout=timeout, follow_redirects=True) as owned:
                response = owned.get(url, headers=headers)
                return response.status_code, response.content
        except Exception as exc:
            # httpx.TimeoutException and its subclasses, without importing httpx.
            if any("Timeout" in cls.__name__ for cls in type(exc).__mro__):
                raise VehiclesDBTimeoutError(url, exc)
            raise

    return _fetch


# --------------------------------------------------------------------------
# client
# --------------------------------------------------------------------------

class VehiclesDB:
    """Client for the VehiclesDB open dataset and (where it exists) the API.

    ```python
    from vehiclesdb import VehiclesDB

    db = VehiclesDB()
    db.models("VW", kind="car")
    db.resolve("VW Golf", kind="car").id   # "car/volkswagen/golf"
    ```
    """

    def __init__(
        self,
        version: str = "latest",
        dataset_base_url: Optional[str] = None,
        api_base_url: str = DEFAULT_API_BASE_URL,
        api_key: Optional[str] = None,
        transport: Any = None,
        timeout: float = 10.0,
    ) -> None:
        """
        :param version: git tag of the data repo to read, e.g. ``"2026.07.6"``.
            ``"latest"`` follows the newest release; pin a version in
            production so a monthly data release cannot change your answers
            underneath you (versions are ``YYYY.MM.PATCH`` — the version IS the
            freshness).
        :param dataset_base_url: override the CDN base entirely (a mirror, a
            local checkout served over HTTP, an internal proxy). When set,
            ``version`` is ignored — you are pinning by URL instead.
        :param api_base_url: host for the hosted API. Only ``images()`` uses it.
        :param api_key: enables ``images()``. Sent as ``Authorization: Bearer``.
        :param transport: either a ``transport(url, headers) -> (status, bytes)``
            callable, or an ``httpx.Client``-like object (anything with
            ``.get(url, headers=...)``), which is wrapped automatically. This
            is the injection point that keeps the test suite offline.
        :param timeout: seconds, applied by the built-in transports.
        """
        self.version = version
        self.dataset_base_url = (
            dataset_base_url.rstrip("/")
            if dataset_base_url
            else DATASET_BASE_URL_TEMPLATE.format(version=version)
        )
        self.api_base_url = api_base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout

        if transport is None:
            self._transport: Transport = urllib_transport(timeout)
        elif callable(transport):
            self._transport = transport
        elif hasattr(transport, "get"):
            # Duck-typed so we never `import httpx` to do an isinstance check.
            self._transport = httpx_transport(transport, timeout)
        else:
            raise TypeError(
                "transport must be a callable(url, headers) -> (status, bytes) "
                "or an httpx.Client-like object with .get(url, headers=...)"
            )

        # --- memoized state. Nothing below is populated in __init__: building
        # a client must not touch the network (see this module's docstring).
        self._dist: Optional[Dict[str, Any]] = None
        self._makes: List[Make] = []
        self._makes_by_slug: Dict[str, Make] = {}
        self._make_keys: Dict[str, str] = {}          # folded key -> make slug
        self._make_lookup: Dict[str, str] = {}        # lowercased name/slug/alias -> make slug
        self._models: List[Model] = []
        self._models_by_id: Dict[str, Model] = {}
        self._models_by_make: Dict[str, List[Model]] = {}
        self._former_ids: Dict[str, List[Model]] = {}
        # Global folded indexes for the make-independent half of rung 3. Built
        # once at index time rather than scanned per call: the release is 15,677
        # models, and resolve() must not be O(corpus).
        self._alias_index: Dict[str, List[Model]] = {}
        self._name_index: Dict[str, List[Model]] = {}
        self._catalogs: Dict[str, Dict[str, Dict[str, Any]]] = {}

    # -- attribution -------------------------------------------------------

    @property
    def attribution(self) -> str:
        """The CC-BY notice, so integrators render credit without copying prose.

        Visible credit with a link is a condition of the licence (CC-BY 4.0
        §3(a)), not a courtesy. See ``attribution_html`` for a ready-to-embed
        footer link.
        """
        return ATTRIBUTION_TEXT

    @property
    def attribution_html(self) -> str:
        """The exact snippet the data repo's README asks for, as HTML."""
        return ATTRIBUTION_HTML

    # -- dataset metadata --------------------------------------------------

    @property
    def dataset_version(self) -> str:
        """The release actually loaded, e.g. ``"2026.07.6"``. Triggers the fetch.

        Read this rather than trusting ``self.version``: ``"latest"`` resolves
        to whatever tag the CDN is serving right now, and logging the concrete
        version is how a support ticket becomes reproducible.
        """
        return str(self._dataset()["version"])

    @property
    def kinds(self) -> List[str]:
        """Vehicle kinds present in this release, e.g. ``["bus", "car", ...]``."""
        return list(self._dataset()["kinds"])

    # -- the contract surface ---------------------------------------------

    def makes(self, kind: Optional[str] = None) -> List[Make]:
        """Every published make, or only those that build `kind`.

        With no ``kind`` this is the union across kinds — a make appears once,
        carrying all its kinds (Ford is ``["car", "van", "truck", "bus"]``).
        With a ``kind`` it filters on that published ``kinds[]`` list, which is
        the make's own declaration, not an inference from the models we happen
        to hold.
        """
        self._dataset()
        if kind is None:
            return list(self._makes)
        return [m for m in self._makes if kind in m.kinds]

    def models(
        self,
        make: str,
        kind: Optional[str] = None,
        body_type: Optional[str] = None,
    ) -> List[Model]:
        """Models of one make. The make lookup is alias-aware and forgiving.

        ``models("VW")``, ``models("vw")``, ``models("Volkswagen")`` and
        ``models("volkswagen")`` are the same call, because ``"VW"`` is a
        published make alias.

        An unknown make returns ``[]``, never an exception — same promise the
        Ruby gem makes ("Unknown make? You get an empty array"). A picker fed
        user input should not be able to crash a request.

        Returned in the dataset's own order: kind, then slug. Deterministic and
        identical in every SDK, which is the point.
        """
        self._dataset()
        slug = self._lookup_make_slug(make)
        if slug is None:
            return []
        found = self._models_by_make.get(slug, [])
        if kind is not None:
            found = [m for m in found if m.kind == kind]
        if body_type is not None:
            # dist/ publishes the PRIMARY body type only; the catalog's full
            # `body_types[]` needs an extra fetch, and models() promises not to
            # make one. Filtering on the primary is the honest reading of the
            # projection we are holding.
            found = [m for m in found if m.body_type == body_type]
        return list(found)

    def model(self, *parts: str) -> Optional[Model]:
        """One full record, by canonical id — ``model("car/volkswagen/golf")``
        or ``model("car", "volkswagen", "golf")``.

        Honours ``former_ids``: an id that was renamed in a past release still
        resolves to the current record, which is the whole "old ids keep
        working" promise (``model("car/alfa-romeo/1750gtv")`` returns
        ``car/alfa-romeo/1750-gtv``). Unknown id returns ``None``.

        This is the ONLY method that fetches ``catalog/{kind}/models.json``,
        and it does so lazily and once per kind. That file carries the depth
        the lean ``dist`` projection drops: full ``body_types[]``, per-country
        ``popularity``, ``sources``, and type-approval ``xrefs``.
        """
        vehicle_id = _join_id(parts)
        self._dataset()
        lean = self._models_by_id.get(vehicle_id)
        if lean is None:
            former = self._former_ids.get(vehicle_id)
            if not former:
                return None
            lean = pick_collision(former)
        return self._with_catalog(lean)

    def _resolver(self):
        self._dataset()
        if not hasattr(self, '_resolution_engine'):
            from ._resolution import Resolver
            self._resolution_engine = Resolver(self)
        return self._resolution_engine

    def model_match(self, make: str, model: str, kind: Optional[str] = None,
                    country: Optional[str] = None,
                    kinds: Optional[Iterable[str]] = None) -> Optional[Resolution]:
        """Resolve separate fields with the RESOLUTION.md ladder.

        ``kind`` scopes the name rungs; ``kinds`` is a hard filter on every
        rung (``[]`` matches nothing) — RESOLUTION.md §3a.
        """
        return self._resolver().pair(make, model, kind, country, _kinds(kinds))

    def resolve(self, query: str, kind: Optional[str] = None,
                country: Optional[str] = None,
                kinds: Optional[Iterable[str]] = None) -> Optional[Resolution]:
        """Best effort text resolution; None for no match, a result for ambiguity.

        ``kind`` scopes the name rungs (an explicit id still answers);
        ``kinds`` is a hard filter on every rung, ids included.
        """
        return self._resolver().text(query, kind, country, _kinds(kinds))

    def by_id(self, vehicle_id: str, follow: bool = True,
              kinds: Optional[Iterable[str]] = None) -> Optional[Model]:
        """A light record by canonical id, from the one dataset fetch.

        Unlike ``model()`` this never fetches the per-kind catalog. With
        ``follow`` (default) a former id lands on the record that replaced it.
        ``kinds`` is a hard filter. Unknown id: ``None``.
        """
        key = _join_id((vehicle_id,))
        self._dataset()
        allowed = _kinds(kinds)
        ok = (lambda m: True) if allowed is None else (lambda m: m.kind in allowed)
        live = self._models_by_id.get(key)
        if live is not None:
            return live if ok(live) else None
        if not follow:
            return None
        candidates = [m for m in self._former_ids.get(key, []) if ok(m)]
        return pick_collision(candidates) if candidates else None

    def successor(self, vehicle_id: str) -> Optional[str]:
        """The live canonical id for a stored id: the id itself when live, its
        successor when a release renamed or merged it, ``None`` when unknown."""
        model = self.by_id(vehicle_id, follow=True)
        return model.id if model is not None else None

    def catalog(self, kind: Optional[str] = None, country: Optional[str] = None,
                kinds: Optional[Iterable[str]] = None) -> List[Dict[str, Any]]:
        """Picker data: ``[{"make": Make, "models": [Model, ...]}, ...]``.

        Makes in name order, models in name order, filtered by ``kind`` /
        ``kinds`` and by ``country`` (models with register evidence there;
        makes left with no model are dropped). One dataset fetch.
        """
        self._dataset()
        allowed = _kinds(kinds)
        cc = country.strip().lower() if country else None
        out = []
        for make in sorted(self._makes, key=lambda m: (fold(m.name), m.slug)):
            models = [m for m in self._models_by_make.get(make.slug, [])
                      if (kind is None or m.kind == kind) and (allowed is None or m.kind in allowed)
                      and (cc is None or cc in m.availability)]
            if not models:
                continue
            models.sort(key=lambda m: (fold(m.name), m.id))
            out.append({"make": make, "models": models})
        return out

    # -- reference labels (no I/O) -----------------------------------------

    def colors(self, locale: Optional[str] = None) -> List[Dict[str, str]]:
        """The canonical 14-colour palette: ``[{"slug", "name", "hex"}]``, names in ``en``/``es``."""
        lang = locale_of(locale)
        return [{"slug": slug, "name": names[lang], "hex": hex_} for slug, hex_, names in COLORS]

    def color_options(self, locale: Optional[str] = None) -> List[Tuple[str, str]]:
        """``[(label, slug), ...]`` for a select — the gem's ``color_options``."""
        return [(c["name"], c["slug"]) for c in self.colors(locale)]

    def color(self, query: str, locale: Optional[str] = None) -> Optional[Dict[str, str]]:
        """A palette colour from a slug or an English/Spanish name or synonym
        (``"gris"``, ``"Marrón"``, ``"navy"``), or ``None``."""
        q = fold(query)
        if not q:
            return None
        slug = next((s for s, _, names in COLORS if s == q or any(fold(n) == q for n in names.values())), None)
        slug = slug or COLOR_SYNONYMS.get(q)
        return next((c for c in self.colors(locale) if c["slug"] == slug), None) if slug else None

    def kind_label(self, kind: str, locale: Optional[str] = None) -> Optional[str]:
        """``"Coche"`` for ``kind_label("car", "es")``. Unknown kind: ``None``."""
        labels = KIND_LABELS.get(str(kind or "").strip().lower())
        return labels[locale_of(locale)] if labels else None

    def body_type_label(self, body_type: str, locale: Optional[str] = None) -> Optional[str]:
        """``"Familiar"`` for ``body_type_label("wagon", "es")``. Unknown: ``None``."""
        labels = BODY_TYPE_LABELS.get(str(body_type or "").strip().lower())
        return labels[locale_of(locale)] if labels else None

    def search(self, query: str, kind: Optional[str] = None, limit: int = 25) -> List[Model]:
        """Ranked substring search over model names — an autocomplete endpoint.

        Ranking, in tiers (a lower tier always beats a higher one, whatever the
        popularity):

        0. the folded query equals the folded model name
        1. the model name starts with the query
        2. the query appears anywhere in the name
        3. the query matches a published alias (a nickname never outranks a
           real name)

        Within a tier: ``global_decile`` ascending (1 = most popular, unranked
        last), then name, then canonical id. The id tie-break is there so the
        order is TOTAL — three makes ship a "Sprinter" with the same decile and
        the same name, and a stable order is what lets the SDKs assert parity.
        """
        self._dataset()
        needle = fold(query)
        if not needle:
            return []

        scored = []
        for model in self._models:
            if kind is not None and model.kind != kind:
                continue
            tier = self._search_tier(model, needle)
            if tier is None:
                continue
            scored.append((tier,) + _popularity_key(model) + (model,))
        scored.sort(key=lambda row: row[:-1])
        return [row[-1] for row in scored[: max(0, limit)]]

    def images(
        self,
        *parts: str,
        **options: Any
    ) -> Dict[str, Any]:
        """Images for one model. **API only — needs an API key.**

        ``db.images("car/renault/clio", color="blue")`` or
        ``db.images("car", "renault", "clio", color="blue")``.

        ``GET /api/v1/vehicles/{kind}/{make}/{model}/images``. There is no dataset
        fallback: the open dataset contains identity and structure, not
        imagery, so a local answer would be a fiction. Without ``api_key`` you
        get ``MissingApiKeyError`` rather than an empty result.

        Returns the endpoint's JSON verbatim — ``id``, ``color``,
        ``requested_color``, ``palette``, ``variants`` (``sm``/``md``/``lg``,
        each ``url``/``width``/``height``), ``format``, ``provenance``. The
        variant URLs are signed and key-free, so they can go straight into an
        ``<img src>`` without leaking your key into markup.

        Colour matching is honest by design: ask for a colour that exists and
        you get it, ask for one not available yet and the API serves a sensible
        fallback — compare ``color`` (served) against ``requested_color``
        (asked). A colour outside the canonical 14-colour palette is a 422.

        :param color: palette colour slug; the API defaults to ``grey``.
        :param format: ``"webp"`` (API default) or ``"png"``.
        :raises MissingApiKeyError: no ``api_key`` on the client.
        :raises VehiclesDBApiError: any non-200, with ``.status``, ``.body`` and
            ``.code``; typed subclasses for 401/403 (``VehiclesDBAuthError``),
            402 (``VehiclesDBPaymentRequiredError``), 404
            (``VehiclesDBNotFoundError``: ``.code`` is ``unknown_model`` when
            the id is not in the API's dataset, ``no_image`` when the vehicle
            has no image yet) and 429 (``VehiclesDBRateLimitError``,
            ``.retry_after``). 422 ``unknown_color`` / ``invalid_format`` /
            ``unsupported_filter`` stay plain ``VehiclesDBApiError``.
        :raises VehiclesDBTimeoutError: no response within ``timeout``.
        """
        unknown = set(options) - {"color", "format"}
        if unknown:
            # `year` and `trim` are RESERVED filters that 422 upstream on
            # purpose, so no integration builds on unimplemented semantics.
            # Rejecting
            # unknown kwargs locally means the same doctrine costs no round
            # trip, and misspelling `colour` is a TypeError, not a silent grey.
            raise TypeError("images() got unexpected keyword arguments: %s" % ", ".join(sorted(unknown)))
        if not self.api_key:
            raise MissingApiKeyError("images")

        vehicle_id = _join_id(parts)
        path = "/api/v1/vehicles/%s/images" % "/".join(
            urllib.parse.quote(segment, safe="") for segment in vehicle_id.split("/")
        )
        params = {k: v for k, v in options.items() if v is not None}
        url = self.api_base_url + path
        if params:
            url += "?" + urllib.parse.urlencode(sorted(params.items()))

        status, body = self._transport(url, self._api_headers())
        payload = _decode_json(body, url)
        if status != 200:
            raise api_error(status, payload, url)
        if not isinstance(payload, dict):
            raise VehiclesDBApiError(status, payload, url)
        return payload

    # -- internals ---------------------------------------------------------

    def _api_headers(self) -> Dict[str, str]:
        # The API authenticates with a bearer token (401 -> VehiclesDBAuthError).
        headers = {
            "Accept": "application/json",
            "User-Agent": "vehiclesdb-python/%s (+https://vehiclesdb.com)" % __version__,
        }
        if self.api_key:
            headers["Authorization"] = "Bearer %s" % self.api_key
        return headers

    def _dataset_headers(self) -> Dict[str, str]:
        # No Authorization: the dataset is CC-BY and served by a public CDN.
        # Sending a key to jsDelivr would leak it to a third party.
        return {
            "Accept": "application/json",
            "User-Agent": "vehiclesdb-python/%s (+https://vehiclesdb.com)" % __version__,
        }

    def _dataset(self) -> Dict[str, Any]:
        """Fetch + index `dist/vehicles.json` exactly once."""
        if self._dist is not None:
            return self._dist
        url = "%s/dist/vehicles.json" % self.dataset_base_url
        payload = self._fetch_dataset_json(url)
        if not isinstance(payload, dict) or not isinstance(payload.get("makes"), list):
            raise DatasetError("dataset has no makes[] — not a vehicles.json?", url)
        self._index(payload)
        self._dist = payload
        return payload

    def _fetch_dataset_json(self, url: str) -> Any:
        status, body = self._transport(url, self._dataset_headers())
        if status != 200:
            raise DatasetError("dataset fetch failed with HTTP %s" % status, url, status)
        try:
            return json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise DatasetError("dataset is not valid UTF-8 JSON: %s" % exc, url)

    def _index(self, payload: Dict[str, Any]) -> None:
        """Build every lookup table in one pass over the release.

        Sorted by slug rather than trusting file order, because determinism is
        the thing the SDKs are asserting against each other and a release is
        free to reorder.

        Everything is built into locals and published at the end, so a
        malformed release leaves the client un-indexed and retryable instead of
        half-indexed and quietly wrong.
        """
        self._kinds = list(payload.get("kinds", []))
        makes: List[Make] = []
        makes_by_slug: Dict[str, Make] = {}
        make_keys: Dict[str, str] = {}
        make_lookup: Dict[str, str] = {}
        all_models: List[Model] = []
        models_by_id: Dict[str, Model] = {}
        models_by_make: Dict[str, List[Model]] = {}
        former_ids: Dict[str, List[Model]] = {}
        alias_index: Dict[str, List[Model]] = {}
        name_index: Dict[str, List[Model]] = {}

        for raw_make in sorted(payload["makes"], key=lambda m: m["slug"]):
            make = Make(
                # dist/ makes carry no `id`; in catalog/{kind}/makes.json the
                # id and the slug are the same string for every make in the
                # release, so the slug IS the make id.
                id=raw_make["slug"],
                slug=raw_make["slug"],
                name=raw_make["name"],
                kinds=list(raw_make.get("kinds", [])),
                countries=None,  # not in this projection — see Make's docstring
                aliases=list(raw_make.get("aliases") or []),
                former_slugs=list(raw_make.get("former_slugs") or []),
            )
            makes.append(make)
            makes_by_slug[make.slug] = make

            # Lookup keys for models(): everything a user might type for this
            # make. First writer wins so a collision is resolved by slug order
            # rather than by file order.
            for key in _make_key_variants(make):
                make_lookup.setdefault(key.lower(), make.slug)
                folded = fold(key)
                if folded:  # see _prefix_keys(): an empty key matches everything
                    make_keys.setdefault(folded, make.slug)

            bucket: List[Model] = []
            for raw_model in sorted(raw_make.get("models", []), key=lambda m: (m["kind"], m["slug"])):
                model = Model(
                    id="%s/%s/%s" % (raw_model["kind"], make.slug, raw_model["slug"]),
                    make_id=make.slug,
                    make_name=make.name,
                    slug=raw_model["slug"],
                    name=raw_model["name"],
                    kind=raw_model["kind"],
                    body_type=raw_model.get("body_type"),
                    aliases=list(raw_model.get("aliases") or []),
                    forms=list(raw_model.get("forms") or []),
                    former_ids=list(raw_model.get("former_ids") or []),
                    global_decile=raw_model.get("global_decile"),
                    mass_decile=raw_model.get("mass_decile"),
                    registration_years=_years(raw_model.get("registration_years")),
                    availability=list(raw_model.get("availability", [])),
                    regions=list(raw_model.get("regions", [])),
                    raw=raw_model,
                )
                bucket.append(model)
                all_models.append(model)
                models_by_id[model.id] = model
                for former in model.former_ids or ():
                    # A former id can be claimed by more than one current
                    # record (a merge), so this is a list and the winner is
                    # picked by the same deterministic popularity key as
                    # everywhere else.
                    former_ids.setdefault(former.lower(), []).append(model)

                # Rung 3's make-independent half needs to know, for one folded
                # string, every record that publishes it as an alias AND every
                # record whose own name or slug is it. Both halves matter: the
                # second is purely an AMBIGUITY signal (a bare name never
                # resolves on its own — contract rule 2), and it is what makes
                # "Rabbit" refuse in the full release, where it is an alias of
                # car/volkswagen/golf and the name of car/volkswagen/rabbit.
                for alias in model.aliases or ():
                    folded_alias = fold(alias)
                    if folded_alias:
                        alias_index.setdefault(folded_alias, []).append(model)
                for key in {fold(model.name), fold(model.slug)}:
                    if key:
                        name_index.setdefault(key, []).append(model)
            models_by_make[make.slug] = bucket

        # A merged/renamed make's old slug lands on its successor — after every
        # real name, alias and slug has claimed its key.
        for make in makes:
            for former in make.former_slugs:
                make_lookup.setdefault(former.lower(), make.slug)
                if fold(former):
                    make_keys.setdefault(fold(former), make.slug)

        self._makes = makes
        self._makes_by_slug = makes_by_slug
        self._make_keys = make_keys
        self._make_lookup = make_lookup
        self._models = all_models
        self._models_by_id = models_by_id
        self._models_by_make = models_by_make
        self._former_ids = former_ids
        self._alias_index = alias_index
        self._name_index = name_index

    def _lookup_make_slug(self, make: str) -> Optional[str]:
        """Alias-aware, forgiving make lookup for models(). None if unknown."""
        if not make:
            return None
        text = make.strip()
        slug = self._make_lookup.get(text.lower())
        if slug is not None:
            return slug
        # Folded fallback so "mercedes benz" finds "Mercedes-Benz" and
        # "citroen" finds "Citroën".
        return self._make_keys.get(fold(text))

    @staticmethod
    def _search_tier(model: Model, needle: str) -> Optional[int]:
        name = fold(model.name)
        if name == needle:
            return 0
        if name.startswith(needle):
            return 1
        if needle in name:
            return 2
        for alias in model.aliases or ():
            if needle in fold(alias):
                return 3
        return None

    def _with_catalog(self, lean: Model) -> Model:
        """Merge the per-kind catalog record into the lean dist projection."""
        record = self._catalog(lean.kind).get(lean.id)
        if record is None:
            # The catalog slice for this kind exists but has no row for this
            # id — a release inconsistency, not a caller error. Hand back the
            # lean projection (which is still correct) rather than raise: the
            # depth is absent, and absent means "not catalogued", per the
            # SCHEMA.md absence rule.
            return lean
        popularity = record.get("popularity") or {}
        return Model(
            id=lean.id,
            make_id=record.get("make_id", lean.make_id),
            make_name=lean.make_name,  # catalog models.json carries no make name
            slug=record.get("slug", lean.slug),
            name=record.get("name", lean.name),
            kind=record.get("kind", lean.kind),
            body_type=lean.body_type,
            body_types=list(record["body_types"]) if record.get("body_types") else None,
            aliases=list(record["aliases"]) if record.get("aliases") else lean.aliases,
            forms=list(record["forms"]) if record.get("forms") else lean.forms,
            former_ids=list(record["former_ids"]) if record.get("former_ids") else lean.former_ids,
            global_decile=popularity.get("global_decile", lean.global_decile),
            mass_decile=popularity.get("mass_decile", lean.mass_decile),
            registration_years=_years(record.get("registration_years")) or lean.registration_years,
            popularity=record.get("popularity"),
            # Project the catalog's evidence rows down to bare country codes so
            # `availability` has one type no matter which file answered; the
            # rows themselves survive in `raw["availability"]`.
            availability=_countries(record.get("availability"), lean.availability),
            regions=list(record.get("regions", lean.regions)),
            sources=list(record["sources"]) if record.get("sources") else None,
            xrefs=record.get("xrefs"),
            raw=record,
        )

    def _catalog(self, kind: str) -> Dict[str, Dict[str, Any]]:
        """Fetch `catalog/{kind}/models.json` once per kind, keyed by canonical id."""
        cached = self._catalogs.get(kind)
        if cached is not None:
            return cached
        url = "%s/catalog/%s/models.json" % (self.dataset_base_url, urllib.parse.quote(kind, safe=""))
        payload = self._fetch_dataset_json(url)
        if not isinstance(payload, list):
            raise DatasetError("catalog slice is not an array", url)
        # The catalog's own `id` is `make/model` — kind-scoped by the FILE, not
        # by the string (SCHEMA.md). Rebuild the three-part canonical id here so
        # it lines up with dist/ ids and with `former_ids`, which ARE
        # kind-qualified inside the very same records.
        index = {
            "%s/%s/%s" % (record.get("kind", kind), record["make_id"], record["slug"]): record
            for record in payload
        }
        self._catalogs[kind] = index
        return index


# --------------------------------------------------------------------------
# module helpers
# --------------------------------------------------------------------------

def _make_key_variants(make: Make) -> List[str]:
    keys = [make.name, make.slug]
    keys.extend(make.aliases or ())
    return keys


def _popularity_key(model: Model) -> Tuple[int, str, str]:
    """The one deterministic ordering used by search() and by every tie-break.

    global_decile ascending (1 = most popular), unranked last, then name, then
    canonical id so the order is total.
    """
    decile = model.global_decile if model.global_decile is not None else _UNRANKED
    return (decile, model.name, model.id)


def _kind_rank(kind: str) -> int:
    return KIND_PRECEDENCE.index(kind) if kind in KIND_PRECEDENCE else len(KIND_PRECEDENCE)


def pick_collision(candidates: Sequence[Model]) -> Model:
    """One record out of ONE nameplate published in several kinds.

    Iveco's Daily is a bus, a truck and a van. The tie-break of RESOLUTION.md
    §3a, identical on every VehiclesDB surface: lowest ``mass_decile``
    (unranked last), then kind precedence van, car, bus, truck, moped,
    motorcycle (any other kind after these, ordinal), then the id (ordinal).
    Pass ``kind=``/``kinds=`` to say what you actually meant.
    """
    return min(candidates, key=lambda m: (
        m.mass_decile if m.mass_decile is not None else _UNRANKED, _kind_rank(m.kind), m.kind, m.id))


def _kinds(kinds: Optional[Iterable[str]]) -> Optional[frozenset]:
    """``kinds`` option: None = every kind, a list = only those ([] = nothing)."""
    if kinds is None:
        return None
    if isinstance(kinds, str):
        return frozenset([kinds])
    return frozenset(kinds)


def _years(value: Any) -> Optional[Dict[str, Optional[int]]]:
    if not isinstance(value, dict):
        return None
    return {"first": value.get("first"), "last": value.get("last")}


def _join_id(parts: Sequence[str]) -> str:
    """Accept ``"car/volkswagen/golf"`` or ``("car", "volkswagen", "golf")``."""
    if len(parts) == 1:
        vehicle_id = parts[0]
    elif len(parts) == 3:
        vehicle_id = "/".join(parts)
    else:
        raise TypeError(
            'expected a canonical id ("car/volkswagen/golf") or three parts '
            '("car", "volkswagen", "golf"), got %d argument(s)' % len(parts)
        )
    if not isinstance(vehicle_id, str):
        raise TypeError("vehicle id must be a string, got %r" % type(vehicle_id).__name__)
    # Ids are lowercase ASCII by construction (SCHEMA.md); lowering here means
    # a caller who stored "Car/Volkswagen/Golf" still gets an answer.
    return vehicle_id.strip().strip("/").lower()


def _countries(rows: Any, fallback: List[str]) -> List[str]:
    if not isinstance(rows, list):
        return list(fallback)
    out = []
    for row in rows:
        if isinstance(row, dict):
            country = row.get("country")
            if country:
                out.append(country)
        elif isinstance(row, str):
            out.append(row)
    return out


def _decode_json(body: bytes, url: str) -> Any:
    """Decode an API body, tolerating a non-JSON error page.

    A proxy or WAF in front of the API can return HTML for a 502; that must
    surface as VehiclesDBApiError(502, "<html>...") rather than a JSONDecodeError
    from somewhere deep in this package.
    """
    try:
        return json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        try:
            return body.decode("utf-8", "replace")
        except Exception:  # pragma: no cover - decode with "replace" cannot fail
            return repr(body)


__all__ = [
    "VehiclesDB",
    "urllib_transport",
    "httpx_transport",
    "ATTRIBUTION_TEXT",
    "ATTRIBUTION_HTML",
    "DATASET_BASE_URL_TEMPLATE",
    "DEFAULT_API_BASE_URL",
    "VehiclesDBError",
    "KIND_PRECEDENCE",
    "pick_collision",
    "__version__",
]
