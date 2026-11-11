# The VehiclesDB SDK contract

This file is identical in [`vehiclesdb-js`](https://github.com/vehiclesdb/vehiclesdb-js)
(npm `@vehiclesdb/client`) and
[`vehiclesdb-python`](https://github.com/vehiclesdb/vehiclesdb-python)
(PyPI `vehiclesdb`). It is the normative description of what every VehiclesDB
client library does, and the reason the clients can be held to it.

Every SDK exists to put one thing into your codebase: the canonical vehicle id

```
kind/make_slug/model_slug        e.g.  car/volkswagen/golf
```

Two requirements follow:

1. **The SDKs must agree.** If `resolve("vw golf")` returns
   `car/volkswagen/golf` in Ruby, it returns `car/volkswagen/golf` in
   JavaScript and in Python. Otherwise the id is three dialects, not a standard.
2. **The SDKs must work without an account.** Every client answers from the
   published open dataset by default (**dataset mode**) and calls the hosted API
   only where the API has something the dataset does not (**API mode**).

| | package | repository |
|---|---|---|
| Ruby | [`vehicles`](https://rubygems.org/gems/vehicles) | [vehiclesdb/vehicles](https://github.com/vehiclesdb/vehicles) — **the reference implementation**; its vocabulary is the one to match |
| JavaScript / TypeScript | [`@vehiclesdb/client`](https://www.npmjs.com/package/@vehiclesdb/client) | [vehiclesdb/vehiclesdb-js](https://github.com/vehiclesdb/vehiclesdb-js) |
| Python | [`vehiclesdb`](https://pypi.org/project/vehiclesdb/) | [vehiclesdb/vehiclesdb-python](https://github.com/vehiclesdb/vehiclesdb-python) |
| Dataset | CC-BY 4.0 | [vehiclesdb/vehiclesdb](https://github.com/vehiclesdb/vehiclesdb) (`SCHEMA.md`, `RESOLUTION.md`, `conformance/`) |

---

## Dataset mode and API mode

| | dataset mode (default) | API mode |
|---|---|---|
| needs a key | no | yes |
| answers from | the published CC-BY dataset, `https://cdn.jsdelivr.net/gh/vehiclesdb/vehiclesdb@{version}` | `https://vehiclesdb.com/api/v1` |
| methods | `makes` `models` `model` `byId`/`by_id` `successor` `catalog` `modelMatch`/`model_match` `resolve` `search`, the colour/kind/body-type labels | `images` |

- **Dataset mode** reads the same release files the Ruby gem refreshes from,
  so all three SDKs read the same bytes. Constructing a client makes no
  request. The light dataset (`dist/vehicles.json`) is fetched once, lazily,
  on the first question, and memoized. Only `model()` reads a second file,
  `catalog/{kind}/models.json`, which carries the per-country popularity,
  sources and crosswalks.
- **API mode** is used only by `images()`. Vehicle imagery is not part of the
  open dataset, so there is no local answer to fall back to. Without a key the
  method raises a configuration error naming the missing option. It never
  returns a placeholder.
- `version` pins a release tag (for example `2026.11.1`); `latest` follows the
  newest one. Pin it when answers must be reproducible.
- A result's `source` is `"dataset"` or `"api"`, so a caller can always see
  which one answered.

### Surface

| method | returns | dataset-mode behaviour |
|---|---|---|
| `makes(kind?)` | list of Make | filter the published make list |
| `models(make, kind?, body_type?)` | list of Model | alias-aware make lookup, then filter; an unknown make gives an empty list |
| `model(id)` / `model(kind, make, slug)` | Model or null | id lookup that honours `former_ids` |
| `modelMatch(make, model, …)` / `model_match(make, model, …)` | Resolution or null | the pair resolution ladder |
| `resolve(text, kind?, country?)` | Resolution or null | the text resolution ladder |
| `search(query, kind?, limit=25)` | ranked list of Model | local ranked substring match |
| `byId(id, follow=true, kinds?)` / `by_id(...)` | Model (light) or null | exact id, then (with `follow`) the record a former id moved to; no catalog fetch |
| `successor(id)` | id string or null | the live id for a stored id: itself, its successor, or null |
| `catalog(kind?, kinds?, country?)` | list of `{make, models[]}` | picker data: name-ordered, filtered by kind(s) and register evidence in `country` |
| `colors(locale?)`, `colorOptions`/`color_options(locale?)`, `color(query, locale?)` | palette | the 14-colour palette; names in `en`/`es`; `color()` reads slugs and English/Spanish names |
| `kindLabel`/`kind_label(kind, locale?)`, `bodyTypeLabel`/`body_type_label(...)` | string or null | display labels in `en`/`es` |
| `images(id, color?, format?)` | the endpoint's JSON, verbatim | **API only** |

Endpoints that have not shipped (`stats`, `markets`, `plates`, `vin`,
`resolve/batch`) are deliberately **absent**. A method that throws "not
implemented yet" invites integrations onto semantics that do not exist yet.
Methods are added when their endpoint is live.

---

## Field naming

Field names come from the published schema
([`SCHEMA.md`](https://github.com/vehiclesdb/vehiclesdb/blob/main/SCHEMA.md)).
Do not invent fields and do not rename them. The only change allowed is
language-idiomatic casing: `bodyType` / `formerIds` / `globalDecile` in
JavaScript, `body_type` / `former_ids` / `global_decile` in Python. The
*concepts* and the *values* must match.

```
Make       { id, slug, name, kinds[], countries[]?, aliases[], former_slugs[] }
Model      { id, make_id, make_name, slug, name, kind, body_type|body_types[],
             aliases[], forms[], former_ids[], global_decile|popularity{},
             mass_decile, registration_years{first,last}?, availability[],
             regions[] }
Resolution { id?, kind?, make?, model?, method, confidence, confident, source,
             match, alternates[], candidates[], ambiguous, via[] }
```

- `id` is always the canonical `kind/make_slug/model_slug`.
- Array fields are `[]` when the release has none (never null), in every SDK.
- `registration_years` is a **hint**: the first and last first-registration
  year seen in the registers, not production years, never a validation bound.
  Null until the release publishes it.
- `confident` = not ambiguous and `method` is not `fuzzy`: the recommended
  threshold for applying an answer to stored data without a human.
- `body_type`/`body_types` and `global_decile`/`popularity` are the two
  published projections. The light `dist/vehicles.json` carries the primary
  body type and the global decile, while the per-kind catalog carries the full
  list and the per-country ranks. `model()` fills in both.
- `availability` is a list of country codes in the light file and a list of
  `{country, evidence, source}` objects in the catalog. These are the files'
  own shapes. They agree by construction.
- The schema's **absence rule** is binding: an absent optional field means
  "not catalogued yet", never "no".
- The `images()` response is returned verbatim, snake_case included. It is a
  documented wire contract (<https://vehiclesdb.com/api>).

Two shape traps:

- **`Make.countries` is absent in dataset mode.** `dist/vehicles.json` does not
  carry it; only `catalog/{kind}/makes.json` does. Leave it null rather than
  deriving it, because a derived value could disagree with the catalog.
- **`former_ids` are fully kind-qualified** (`car/alfa-romeo/1750gtv`) even in
  `catalog/{kind}/models.json`, where the record's own `id` is only
  `make/model`. Rebuild the three-part id before comparing them.

---

## Resolution

`resolve(text, …)` and `modelMatch(make, model, …)` / `model_match(...)`
implement
[`RESOLUTION.md`](https://github.com/vehiclesdb/vehiclesdb/blob/main/RESOLUTION.md)
in the dataset repo, and must pass its language-neutral conformance suite,
[`conformance/resolve.json`](https://github.com/vehiclesdb/vehiclesdb/blob/main/conformance/resolve.json).
Knowledge comes only from published data, with no hardcoded vehicle names.

| order | method | confidence | evidence |
|---|---|---|---|
| 1 | `exact` | 1.00 | verbatim canonical id (text only) |
| 2 | `former_id` | 0.98 | full published former id (text only) |
| 3 | `fold` | 0.97 | normalized name/slug, spacing-blind name, then `Serie N` → `N Series` |
| 4 | `alias` | 0.93 | published model alias within the make |
| 5 | `form` | 0.92 | curated spelling within the make |
| 6 | `alias` | 0.90 | whole text is a unique alias, including name collision checks |
| 7 | `cleaned` | 0.90 | peel leading new-fillers / complete make echoes, retry 3–5 |
| 8 | `fuzzy` | 0.80 | bounded word-by-word edit distance |

Confidences label rungs. They are not probabilities.

- **Normalization:** NFKD, then remove `Mn` marks, lowercase, collapse runs of
  non-`[a-z0-9]` to single spaces, and trim. Pair lookups also keep raw
  lowercase equality, for native-script aliases.
- **Uniqueness:** spacing-blind names, aliases and forms must identify one
  nameplate (make + model slug; kind variants count as one). Aliases and forms
  are make-scoped. An ambiguous rung stops the ladder.
- **Kind variants** (RESOLUTION.md §3a): when a rung's winning candidates are
  one nameplate in several kinds, pick by lowest `mass_decile` (unranked
  last), then kind precedence van, car, bus, truck, moped, motorcycle, then id
  (ordinal). Only the records the rung matched compete. `kind` scopes the name
  rungs (an explicit id still answers); `kinds` is a hard filter on every
  rung, ids included (`[]` matches nothing); `country` restricts availability.
- **Make former slugs:** a make input equal to a published `former_slugs`
  value lands on the successor make (`via` `former_make_slug:old→new`).
- **Typos** apply to human-shaped input only. Paths, underscores, `+`,
  backslashes, edge or double hyphens and single-case hyphenated slugs disable
  them for the whole text.
  - Make typos use whole-string optimal string alignment: one edit for 4–5
    characters, two from six. A tie between closest makes means no match.
  - Model typos compare equal word counts with matching initials. A differing
    word must have no digits and at least four letters. One edit is allowed per
    word, or two from nine letters. A tie between nameplates is ambiguous;
    a tie between kinds of one nameplate is a kind variant (above).
  - A make typo caps the answer at `fuzzy` / 0.80, and a model typo never
    stacks on top of it.
- **Result shape:** `id`, `kind`, `make`, `model`, `confidence`, `source`,
  `method`, `match` (`{id, name, make:{id,name}, kind, confidence, method}`),
  `alternates`, `candidates`, `ambiguous` and `via`, the audit trail (for
  example `make_alias:vw→volkswagen` or `form:2008 allure→2008`). No match
  returns null / `None`. An ambiguous result has a null `match`/`id`,
  confidence 0 and the competing records in `alternates`. `matchedOn` /
  `matched_on` is a deprecated alias of `method`.

Answers depend on the corpus. For example, `Rabbit` resolves to the Golf on the
capped test fixtures, but is ambiguous on a full release that also has a
`car/volkswagen/rabbit` record. What must never differ is two SDKs answering
over the same corpus.

---

## Cross-language parity

The Ruby gem [`vehicles`](https://github.com/vehiclesdb/vehicles) is the
reference implementation. JavaScript and Python follow its vocabulary and its
answers, and parity is checked mechanically:

- **Shared fixtures.** Each repo carries `fixtures/`, a verbatim subset of a
  real release (12 makes, 289 models, release `2026.07.6`) in the exact CDN
  layout (`manifest.json`, `dist/vehicles.json`,
  `catalog/{kind}/{makes,models}.json`). The two copies are
  **byte-identical**. They are cut by `tools/make_fixtures.py` from a checkout
  of the public dataset repo, never written by hand:

  ```bash
  git clone https://github.com/vehiclesdb/vehiclesdb ../vehiclesdb
  git -C ../vehiclesdb checkout v2026.07.6
  python3 tools/make_fixtures.py --data-repo ../vehiclesdb
  ```

  After regenerating, copy `fixtures/` to the other SDK repo unchanged.
- **Conformance.** Both test suites run
  [`conformance/resolve.json`](https://github.com/vehiclesdb/vehiclesdb/blob/main/conformance/resolve.json)
  against a full release. The Ruby gem runs the same file.
- **Parity check.** `tools/parity_check.sh`, which is identical in both repos,
  runs the same resolve and pair cases through both SDKs over the same bytes.
  It fails on any difference in id, method, confidence, trail, ambiguity or
  candidates. Run it with the other SDK checked out next to this one:

  ```bash
  bash tools/parity_check.sh                 # against fixtures/
  bash tools/parity_check.sh ../vehiclesdb   # against a full release
  ```

- **Offline tests.** No test may touch the network. The HTTP layer is
  injected (a `fetch`-shaped function in JS, a transport callable in Python),
  and the test transport raises on any URL it has no file for.

---

## Attribution

The dataset is CC-BY 4.0, and **visible credit with a link is a condition of
the licence** (§3(a)). It is not optional. Every SDK documents the notice and
exposes it programmatically, so an integrator can render it without copying
prose:

> Vehicle data by [VehiclesDB](https://vehiclesdb.com)

Upstream register notices (KBA's `dl-de/by-2-0`, RDW's terms, Traficom's
CC-BY, and others) apply under every licence. See
[`ATTRIBUTION.md`](https://github.com/vehiclesdb/vehiclesdb/blob/main/ATTRIBUTION.md),
and link to it instead of paraphrasing a licence statement.

The SDK **code** is MIT.
