"""The three return types: Make, Model, Resolution.

Field names are the PUBLISHED ones (SCHEMA.md in the data repo), snake_cased
because they already are. Nothing here is invented: if a field is not in
SCHEMA.md it is not an attribute, with the two documented exceptions marked
`# SDK-level` below.

The absence rule (SCHEMA.md, "The absence rule (binding)") is load-bearing:
an absent optional key means "not catalogued yet", never "no". So optional
fields default to None, and `to_dict()` OMITS them rather than emitting
`"aliases": null` — round-tripping a record through this package must not
turn "we haven't curated aliases for this model" into "this model has no
aliases".
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# `matched_on` -> confidence, for Resolution.
#
# READ THIS BEFORE USING THE NUMBER: in dataset mode these are *rung labels*
# rendered as floats so a caller can write `if r.confidence >= 0.9`. They are
# not probabilities, they are not calibrated against anything, and no model
# produced them. The graded resolver lives behind `GET /v1/resolve` (see
# CONTRACT.md); when a response comes from there, `confidence` is whatever
# the API said and this table is not consulted.
MATCH_CONFIDENCE = {"exact": 1.0, "former_id": .98, "fold": .97, "alias": .93, "form": .92, "cleaned": .90, "fuzzy": .80}


def _compact(pairs: Dict[str, Any]) -> Dict[str, Any]:
    """Drop None values — see the absence rule in this module's docstring."""
    return {k: v for k, v in pairs.items() if v is not None}


@dataclass(frozen=True)
class Make:
    """A make, as published in `dist/vehicles.json` or `catalog/{kind}/makes.json`.

    `countries` is None in dataset mode. That is not an oversight: the lean
    `dist/vehicles.json` projection that this package reads for makes() does
    not carry it (SCHEMA.md, "dist/vehicles.json (the gem projection)"), and
    deriving it from the models we happen to hold would produce a number that
    quietly disagrees with `catalog/{kind}/makes.json`. None means "not in this
    projection", per the absence rule.
    """

    id: str
    slug: str
    name: str
    kinds: List[str]
    countries: Optional[List[str]] = None
    aliases: Optional[List[str]] = None

    def to_dict(self) -> Dict[str, Any]:
        return _compact(
            {
                "id": self.id,
                "slug": self.slug,
                "name": self.name,
                "kinds": list(self.kinds),
                "countries": list(self.countries) if self.countries is not None else None,
                "aliases": list(self.aliases) if self.aliases is not None else None,
            }
        )


@dataclass(frozen=True)
class Model:
    """A nameplate.

    Two published projections feed this one class, and which one you got is
    visible in the fields:

    * `dist/vehicles.json` (what makes()/models()/resolve()/search() read) —
      carries `body_type` (primary only), `global_decile`, and `availability`
      as bare country codes.
    * `catalog/{kind}/models.json` (what model() reads, one extra fetch) —
      carries `body_types` (the full list), `popularity` (with per-country
      rank/decile/confidence), `sources` and `xrefs`.

    So `body_type` vs `body_types` and `global_decile` vs `popularity` are not
    duplicate fields; they are the two published shapes, and the contract in
    CONTRACT.md spells them as alternatives (`body_type|body_types[]`,
    `global_decile|popularity{}`) for exactly this reason. When model() merges
    the catalog record in, it fills BOTH sides so a caller never has to know
    which file answered.
    """

    # `id` is the product: the canonical `kind/make_slug/model_slug`.
    #
    # GOTCHA: this is NOT the `id` key in `catalog/{kind}/models.json`. That
    # file's `id` is `make_slug/model_slug` with no kind, because the file
    # itself is the kind scope (SCHEMA.md, "Model (nameplate)": `"<make>/<model>"`
    # (kind-scoped by file)). `former_ids` inside the SAME record, however, ARE
    # fully kind-qualified (`car/alfa-romeo/1750gtv`). We always rebuild the
    # three-part form so the two can be compared.
    id: str
    make_id: str
    slug: str
    name: str
    kind: str
    make_name: Optional[str] = None
    body_type: Optional[str] = None
    body_types: Optional[List[str]] = None
    aliases: Optional[List[str]] = None
    forms: Optional[List[str]] = None
    former_ids: Optional[List[str]] = None
    global_decile: Optional[int] = None
    popularity: Optional[Dict[str, Any]] = None
    # Always bare ISO-3166 alpha-2 codes, from EITHER projection. dist/ already
    # publishes them that way; the catalog publishes objects
    # ({"country": "nl", "evidence": "registration", "source": "nl_rdw"}) and we
    # project those down to their `country` so the attribute's TYPE never
    # depends on which file answered. Nothing is lost: the evidence rows are in
    # `raw["availability"]`.
    availability: List[str] = field(default_factory=list)
    regions: List[str] = field(default_factory=list)
    sources: Optional[List[str]] = None
    xrefs: Optional[Dict[str, Any]] = None

    # SDK-level, not schema: the untouched published record this was built
    # from. It is the escape hatch for anything a release adds that this
    # package predates (the reserved `generations`/`variants` layers, new
    # `xrefs` keys), so a new field is never a reason to wait for an SDK
    # release. Excluded from == and from to_dict() because it is not part of
    # the published shape.
    raw: Dict[str, Any] = field(default_factory=dict, compare=False, repr=False)

    @property
    def full_name(self) -> str:
        """"Volkswagen Golf" — the label a picker shows. Mirrors the gem's `full_name`."""
        return "%s %s" % (self.make_name, self.name) if self.make_name else self.name

    def available_in(self, country: str) -> bool:
        """True when an official source evidences this model in `country`.

        Presence, not marketing history (SCHEMA.md, "Availability") — a
        grey-imported JDM model really is available in `nz`.
        """
        return country.lower() in self.availability

    def to_dict(self) -> Dict[str, Any]:
        return _compact(
            {
                "id": self.id,
                "make_id": self.make_id,
                "make_name": self.make_name,
                "slug": self.slug,
                "name": self.name,
                "kind": self.kind,
                "body_type": self.body_type,
                "body_types": list(self.body_types) if self.body_types is not None else None,
                "aliases": list(self.aliases) if self.aliases is not None else None,
                "forms": list(self.forms) if self.forms is not None else None,
                "former_ids": list(self.former_ids) if self.former_ids is not None else None,
                "global_decile": self.global_decile,
                "popularity": self.popularity,
                "availability": list(self.availability),
                "regions": list(self.regions),
                "sources": list(self.sources) if self.sources is not None else None,
                "xrefs": self.xrefs,
            }
        )


@dataclass(frozen=True)
class Resolution:
    """A match or explicit ambiguity. No match at all is returned as None.

    `method` is the contract vocabulary; `matched_on` is a deprecated alias.
    `match` and `alternates` expose the API facts without fetching the catalog.
    """
    id: Optional[str]
    kind: Optional[str]
    make: Optional[str]
    model: Optional[str]
    method: str
    confidence: float
    source: str = "dataset"
    via: List[str] = field(default_factory=list)
    candidates: List[Model] = field(default_factory=list)
    ambiguous: bool = False
    record: Optional[Model] = field(default=None, repr=False)

    @property
    def matched_on(self):
        """Deprecated: use method."""
        return self.method

    @property
    def resolved_via(self):
        return self.via

    @property
    def match(self):
        if self.record is None:
            return None
        return dict(id=self.id, name=self.model, make=dict(id=self.record.make_id, name=self.make),
                    kind=self.kind, confidence=self.confidence, method=self.method)

    @property
    def alternates(self):
        return [m for m in self.candidates if m.id != self.id]

    def to_dict(self):
        return dict(id=self.id, kind=self.kind, make=self.make, model=self.model,
                    method=self.method, matched_on=self.method, confidence=self.confidence,
                    source=self.source, match=self.match, ambiguous=self.ambiguous,
                    alternates=[m.to_dict() for m in self.alternates],
                    candidates=[m.to_dict() for m in self.candidates],
                    via=list(self.via), resolved_via=list(self.via))
