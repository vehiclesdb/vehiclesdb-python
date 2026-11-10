# `vehiclesdb` — vehicle makes, models and canonical ids for Python

[![PyPI](https://img.shields.io/pypi/v/vehiclesdb.svg)](https://pypi.org/project/vehiclesdb/)
[![CI](https://github.com/vehiclesdb/vehiclesdb-python/actions/workflows/ci.yml/badge.svg)](https://github.com/vehiclesdb/vehiclesdb-python/actions/workflows/ci.yml)

`vehiclesdb` gives your Python code a real list of vehicle makes and models —
cars, motorcycles, mopeds, vans, trucks and buses, reconciled from the official
registers of every country the dataset covers — plus one stable id per nameplate:

```
kind/make_slug/model_slug        e.g.  car/volkswagen/golf
```

**That id is the product.** It is the thing to put in your database column. It
survives renames (old ids keep resolving), it is the same id the
[`vehicles`](https://github.com/vehiclesdb/vehicles) Ruby gem and the
`@vehiclesdb/client` JS package use, and it is what the hosted API is keyed on.

Zero required dependencies — `urllib.request` and `json`. Python 3.9+.

## Install

```bash
pip install vehiclesdb
```

Optional: `pip install "vehiclesdb[httpx]"` to use an `httpx` client as the
transport (see below).

## 60 seconds

```python
from vehiclesdb import VehiclesDB

db = VehiclesDB()

db.makes(kind="car")                  # [Make, ...] — every make that builds cars
db.makes()                            # the union across kinds; Ford carries
                                      # kinds == ["car", "van", "truck", "bus"]

db.models("VW", kind="car")           # [Model, ...] — alias-aware make lookup:
                                      # "VW", "vw" and "Volkswagen" are one call

car = db.model("car/volkswagen/golf") # or db.model("car", "volkswagen", "golf")
car.name                              # "Golf"
car.full_name                         # "Volkswagen Golf"
car.body_types                        # ["hatchback", "wagon"]
car.global_decile                     # 2      (top 20% worldwide, from registrations)
car.available_in("nl")                # True   (evidence in the Dutch register)

hit = db.resolve("VW Golf", kind="car")
hit.id                                # "car/volkswagen/golf"
hit.method                            # "fold"
hit.confidence                        # 0.97
hit.via                               # ["make_alias:vw→volkswagen"]
hit.source                            # "dataset"

db.search("golf", limit=10)           # ranked, for an autocomplete endpoint

db.attribution                        # the CC-BY notice — you have to show it
```

An unknown make gives you `[]`, an unknown id gives you `None`, and an
unresolvable query gives you `None`. Nothing here raises on user input.

## Two modes

| | dataset mode (default) | API mode |
|---|---|---|
| where answers come from | the published CC-BY dataset on jsDelivr | `https://vehiclesdb.com/api/v1` |
| needs a key | no | yes |
| `makes` `models` `model` `by_id` `successor` `catalog` `resolve` `model_match` `search`, labels | ✅ local | — |
| `images` | ❌ no local answer exists | ✅ |

Dataset mode is not a stub. The dataset is real, current and complete for what
it covers, and the package fetches it **once, lazily, and memoizes it** —
constructing a client makes no request at all. Only `model()` pulls a second
file (`catalog/{kind}/models.json`), because that is where the per-country
popularity, the source list and the type-approval crosswalks live.

`images()` is the one method that talks to the API, because rendered imagery is
not in the open dataset — there is nothing local to fall back to, so it raises
`MissingApiKeyError` without a key rather than pretending:

```python
db = VehiclesDB(api_key="...")
shot = db.images("car/renault/clio", color="blue")
shot["variants"]["lg"]["url"]   # signed and key-free — safe in an <img src>
shot["color"], shot["requested_color"]   # what you got vs what you asked for
```

Colour matching is honest by design: ask for a colour that is rendered and you
get it; ask for one that is not and the API serves a sensible fallback and
tells you it did. A colour outside the canonical palette is a `422`, never a
silent guess.

Non-2xx responses raise `VehiclesDBApiError` with `.status`, `.body` and
`.code` (the body's `error`, e.g. `"no_render"`; an image 404 is
`unknown_model` when the id is not in the API's dataset, `no_render` when
the vehicle has no render yet). The statuses you handle
differently have their own subclasses: `VehiclesDBAuthError` (401/403: missing,
invalid or revoked key), `VehiclesDBPaymentRequiredError` (402: the wallet is
empty), `VehiclesDBNotFoundError` (404) and `VehiclesDBRateLimitError` (429,
with `.retry_after` in seconds, read from the body's `retry_after`, which the
API always sends). No response within `timeout` raises
`VehiclesDBTimeoutError` (a `TransportError`).

```python
from vehiclesdb import VehiclesDBAuthError, VehiclesDBNotFoundError, VehiclesDBPaymentRequiredError

try:
    shot = db.images("car/volkswagen/passat")
except VehiclesDBNotFoundError:
    shot = None   # no render yet: show your placeholder
except (VehiclesDBAuthError, VehiclesDBPaymentRequiredError):
    raise         # alert someone: every image call fails until the key or wallet is fixed
```

0.1.0 called `/v1/...`, which is not the API's path, so every image call
failed; 0.2.0 calls `/api/v1/...`.

Methods for endpoints that do not exist yet (`stats`, `markets`, `plates`,
`vin`, `resolve/batch`) are deliberately **absent**. A method that 404s is
worse than no method: it invites you to build on semantics nobody has shipped.

### Resolving free text to an id

`resolve()` and `model_match()` implement the published
[resolution contract](https://github.com/vehiclesdb/vehiclesdb/blob/main/RESOLUTION.md)
and pass its conformance suite. They use only published data: names, aliases,
former ids and curated spellings. Each answer says which rung matched
(`method`), a rung label (`confidence`) and how it got there (`via`).

```python
db.resolve("car/volkswagen/golf")     # method "exact",  confidence 1.0
db.resolve("mercedes c class")        # "car/mercedes-benz/c-class", "fold", 0.97
                                      #   via ["make_alias:mercedes→mercedes-benz"]
db.resolve("Peugeot 2008 Allure")     # "car/peugeot/2008", "form", 0.92
                                      #   via ["form:2008 allure→2008"]
db.resolve("Volkswagon Golf")         # "car/volkswagen/golf", "fuzzy", 0.8
                                      #   via ["make_typo:volkswagon→volkswagen"]
db.model_match("BMW", "Serie 3")      # "car/bmw/3-series", "fold", 0.97
db.resolve("golf")                    # None: no make, and the name alone is not unique
```

`model_match(make, model)` is for data that already has the two in separate
columns. Both accept `kind=` (scopes the name rungs; an explicit id still
answers), `kinds=` (a hard filter on every rung, ids included; `[]` matches
nothing) and `country=` to restrict availability.

`r.confident` is `True` when the answer is neither ambiguous nor a typo guess:
the recommended bar for rewriting stored data without a human.

**Kinds.** Some nameplates are published in several kinds (the Iveco Daily is a
bus, a truck and a van). Without a kind every VehiclesDB surface picks the same
one: lowest `mass_decile`, then van, car, bus, truck, moped, motorcycle
([RESOLUTION.md §3a](https://github.com/vehiclesdb/vehiclesdb/blob/main/RESOLUTION.md)).

```python
db.resolve("Iveco Daily").id                     # "van/iveco/daily"
db.resolve("Iveco Daily", kind="truck").id       # "truck/iveco/daily"
db.resolve("bus/iveco/daily", kinds=["car"])     # None: kinds is a hard filter
```

**Stored ids.** Store `id`. When a release renames a record, the old id becomes
a `former_id` of the new one: `db.successor(old_id)` is the id to store now,
`db.by_id(old_id)` the record (one dataset fetch, no catalog call).

```python
db.successor("car/alfa-romeo/1750gtv")   # "car/alfa-romeo/1750-gtv"
```

**Pickers and labels.** `db.catalog(kind="car", country="es")` gives
`[{"make": Make, "models": [Model, ...]}, ...]` for one market, name-ordered.
`db.color_options("es")`, `db.colors("es")`, `db.kind_label("van", "es")`
(`"Furgoneta"`) and `db.body_type_label("wagon", "es")` (`"Familiar"`) carry
English and Spanish labels; `db.color("gris")` reads slugs and English/Spanish
names. `Model.registration_years` (`{"first", "last"}`) is a hint for a year
picker: first-registration years seen in the registers, not production years,
never a validation bound; `None` until the release publishes it.

The ladder is `exact` (1.00) → `former_id` (0.98) → `fold` (0.97) → `alias`
(0.93) → `form` (0.92) → `alias` (0.90) → `cleaned` (0.90) → `fuzzy` (0.80).
Confidences label rungs. They are not probabilities. When two records fit
equally well, the answer is not guessed: the result has `ambiguous=True`, `id`
is `None` and the competing records are in `alternates`. When nothing matches,
the answer is `None`. The full rules are in [`CONTRACT.md`](./CONTRACT.md#resolution).

### `search()`

Ranked substring match over model names, for autocomplete. Tiers, in order:
exact name → name prefix → name substring → published alias. Within a tier:
`global_decile` ascending (1 = most popular, unranked last), then name, then
canonical id. Fully deterministic — a lower tier always beats a higher one, so
a nickname never outranks a real name and a popular model never jumps a tier.

## Version pinning

```python
db = VehiclesDB()                        # follows @latest
db = VehiclesDB(version="2026.11.1")     # pinned — reproducible answers
```

The default base URL is
`https://cdn.jsdelivr.net/gh/vehiclesdb/vehiclesdb@{version}` — the same CDN
base the Ruby gem uses, so all three SDKs demonstrably read the same bytes.

`latest` follows the newest git tag of the data repo. Data lands monthly as
`YYYY.MM.PATCH` — the version *is* the freshness — and a release can add makes,
models, countries and optional fields. That is exactly why you should **pin in
production**: otherwise a Tuesday data release can change what `resolve()`
returns without anything in your code changing. Log `db.dataset_version` (the
version actually loaded) so a bug report is reproducible.

Point somewhere else entirely with `dataset_base_url=` — a mirror, an internal
proxy, or a local checkout served over HTTP.

Scale, as of release `2026.11.1` (read `manifest.json` for current numbers):

| kind | makes | models |
|---|---:|---:|
| car | 323 | 5,888 |
| motorcycle | 267 | 6,142 |
| moped | 317 | 1,429 |
| truck | 97 | 989 |
| van | 134 | 772 |
| bus | 97 | 415 |

(Makes do not sum: one make can build several kinds.)

## Attribution — a licence condition, not a courtesy

The dataset is [CC-BY 4.0](https://creativecommons.org/licenses/by/4.0/). Free
for any use, commercial included. **Visible credit with a link is a condition
of the licence (§3(a)).** The form requested:

> Vehicle data by [VehiclesDB](https://vehiclesdb.com)

```html
<a href="https://vehiclesdb.com">Vehicle data by VehiclesDB</a>
```

So you never have to hand-copy that prose, it is available at runtime:

```python
db.attribution       # "Vehicle data by VehiclesDB (https://vehiclesdb.com), licensed under CC-BY 4.0 ..."
db.attribution_html  # '<a href="https://vehiclesdb.com">Vehicle data by VehiclesDB</a>'
```

- **Website** → a followable link, e.g. in your footer.
- **App with no website** → name VehiclesDB visibly in the app description or
  an about/credits screen.
- **Research / datasets** → cite the repo and the dataset version.

Upstream register notices (KBA's `dl-de/by-2-0`, RDW's terms, Traficom's CC-BY,
and the rest) apply under **every** licence for this data, the commercial one
included — they are the registers' own terms, not VehiclesDB's to waive. They
are listed in
[`ATTRIBUTION.md`](https://github.com/vehiclesdb/vehiclesdb/blob/main/ATTRIBUTION.md);
read it rather than any paraphrase.

The **code** in this package is MIT. The **data** is CC-BY 4.0. See [`LICENSE`](./LICENSE) and [`NOTICE`](./NOTICE).

## HTTP: bring your own, or bring nothing

The default transport is `urllib.request`. Nothing else is required, ever.

A transport is one callable:

```python
transport(url: str, headers: Dict[str, str]) -> Tuple[int, bytes]
```

It returns the status rather than raising on 4xx/5xx, because the API's error
bodies are documented JSON you need to see. Only "no response at all" is an
exception (`TransportError`).

```python
import httpx
from vehiclesdb import VehiclesDB, httpx_transport

client = httpx.Client(timeout=5.0)                       # your pools, your proxies
db = VehiclesDB(transport=httpx_transport(client))
db = VehiclesDB(transport=client)                        # equivalent; duck-typed
```

`httpx` is optional (`pip install "vehiclesdb[httpx]"`) and is **never imported
at module import time** — the import happens inside the transport, only if you
call it. `import vehiclesdb` works on a machine that has never seen httpx.

That same seam is how the tests stay offline: they inject a transport that
serves `fixtures/` off disk and **raises on any URL it has no fixture
for**, so a test cannot silently reach the network.

## Types

Everything comes back as a frozen dataclass with a `to_dict()`, with the
published field names from
[`SCHEMA.md`](https://github.com/vehiclesdb/vehiclesdb/blob/main/SCHEMA.md) —
nothing renamed, nothing invented.

```python
Make       (id, slug, name, kinds, countries?, aliases, former_slugs)
Model      (id, make_id, make_name, slug, name, kind, body_type?, body_types?,
            aliases, forms, former_ids, global_decile?, mass_decile?,
            registration_years?, popularity?, availability, regions, sources?,
            xrefs?)
Resolution (id, kind, make, model, method, confidence, confident, source, match,
            alternates, via, ambiguous)
```

Two things to know about `Model`:

- `body_type`/`body_types` and `global_decile`/`popularity` are not duplicates.
  They are the two published projections: the lean `dist/vehicles.json` (what
  `models()`, `resolve()` and `search()` read) carries the primary body type and
  the global decile; the per-kind catalog (what `model()` reads) carries the
  full list and the per-country ranks. `model()` fills in both sides.
- **The absence rule is binding.** An absent optional field means "not
  catalogued yet", never "no" — so optional scalars and objects are `None` and
  `to_dict()` *omits* them rather than emitting `null`. List fields (`aliases`,
  `forms`, `former_ids`, `former_slugs`) are `[]` when there are none, as in
  the JS SDK and the gem (0.1.0 used `None`).
  Code against presence, not against versions. `Model.raw` is the untouched
  published record if you need a field newer than this package.

## Development

Tests are offline by construction: no test may touch the network.

```bash
pip install pytest
python -m pytest
```

No install step is needed, because the test helpers put `src/` on `sys.path`.
`python -m unittest discover -s tests` works too. The fixtures are a verbatim
subset of a real release (12 makes, 289 models, release `2026.07.6`), cut by
`tools/make_fixtures.py` from the public
[dataset repo](https://github.com/vehiclesdb/vehiclesdb) and byte-identical to
the JS SDK's. That is what makes cross-language parity assertable.

The full-release and conformance layers run against a dataset checkout. They
skip, naming the path they wanted, when it is absent:

```bash
git clone https://github.com/vehiclesdb/vehiclesdb ../vehiclesdb
python -m pytest                      # + full release and conformance from ../vehiclesdb

VDB_DATA_REPO=/path/to/vehiclesdb \
VDB_DATA=/path/to/vehiclesdb/dist/vehicles.json \
VDB_CONFORMANCE=/path/to/vehiclesdb/conformance/resolve.json python -m pytest
```

Parity with the JS SDK is checked by `tools/parity_check.sh`, with
[vehiclesdb-js](https://github.com/vehiclesdb/vehiclesdb-js) checked out next
to this repo. See [`CONTRACT.md`](./CONTRACT.md).

## Related

- [`vehicles`](https://github.com/vehiclesdb/vehicles) — the Ruby gem, the
  reference implementation.
- [`@vehiclesdb/client`](https://www.npmjs.com/package/@vehiclesdb/client) —
  the JavaScript SDK ([repo](https://github.com/vehiclesdb/vehiclesdb-js)),
  same contract.
- [`make-model-dropdown`](https://github.com/vehiclesdb/make-model-dropdown) —
  the browser make → model picker; same resolution contract, offline dataset
  mode, a hidden id field, and an ES module for importmaps.
- [`vehiclesdb/vehiclesdb`](https://github.com/vehiclesdb/vehiclesdb) — the
  open dataset itself (`SCHEMA.md`, `RESOLUTION.md`, `ATTRIBUTION.md`).
- [`CHANGELOG.md`](./CHANGELOG.md)
