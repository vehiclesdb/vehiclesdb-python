# Changelog

All notable changes to `vehiclesdb` are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the package uses
[Semantic Versioning](https://semver.org/). While the version is 0.x, a minor
release may change the API.

## [0.2.0] - unreleased

Dogfooding fixes (VehiclesDB inside CarHey, 2026-11-10). The API changed, hence
the minor bump.

### Fixed

- `images()` now calls `GET /api/v1/vehicles/{kind}/{make}/{model}/images`.
  0.1.0 called `/v1/...`, which the API does not serve, so every image call
  failed.

### Changed

- **Kind collisions** follow RESOLUTION.md §3a, the rule every VehiclesDB
  surface now shares: lowest `mass_decile`, then van, car, bus, truck, moped,
  motorcycle, then id. Unhinted "Iveco Daily" is now `van/iveco/daily`.
- Non-2xx API responses raise typed subclasses of `VehiclesDBApiError`:
  `VehiclesDBAuthError` (401/403), `VehiclesDBPaymentRequiredError` (402),
  `VehiclesDBNotFoundError` (404), `VehiclesDBRateLimitError` (429, with
  `retry_after`). Every API error carries `code`. Timeouts raise
  `VehiclesDBTimeoutError` (a `TransportError`).
- List fields (`aliases`, `forms`, `former_ids`) are `[]` when absent, not
  `None`, matching the JS SDK and the gem.

### Added

- `by_id(id, follow=True, kinds=None)` and `successor(id)` for stored ids.
- `Resolution.confident`: not ambiguous and not a typo guess.
- `kinds=` on `resolve()`/`model_match()`/`by_id()`/`catalog()`: a hard kind
  filter on every rung, ids included.
- `catalog(kind=, country=, kinds=)`: picker data for one market.
- `colors()`, `color_options()`, `color()`, `kind_label()`,
  `body_type_label()` with English and Spanish labels.
- `Model.mass_decile`, `Model.registration_years` (a hint; `None` until the
  release publishes it), `Make.former_slugs`; make resolution follows former
  slugs (`former_make_slug:` in `via`).
- `KIND_PRECEDENCE`, `pick_collision`.

## [0.1.0] - 2026-11-09

First public release.

### Added

- `VehiclesDB` client, with zero required dependencies, Python >= 3.9 support
  and inline type annotations (`py.typed`).
- **Dataset mode** (default, no key): `makes()`, `models()`, `model()`,
  `resolve()`, `model_match()`, `search()` and `dataset_version`, answered from
  the published CC-BY dataset on jsDelivr. Releases can be pinned with
  `version=`. The dataset is fetched lazily and memoized.
- **API mode**: `images()` (0.1.0 called the wrong path; fixed in 0.2.0),
  authenticated with `api_key=`.
- Resolution implements the dataset's `RESOLUTION.md` (exact, former_id, fold,
  alias, form, cleaned and fuzzy rungs, with ambiguity, alternates and an audit
  trail), and passes `conformance/resolve.json` from release 2026.11.1.
- `attribution` / `attribution_html`: the CC-BY 4.0 notice.
- Pluggable transport, with `urllib` as the default and an optional `httpx`
  adapter (`pip install "vehiclesdb[httpx]"`).
- Frozen dataclass models (`Make`, `Model`, `Resolution`) with `to_dict()`.
- `CONTRACT.md`: the cross-language SDK contract shared with the JS SDK and
  the Ruby gem `vehicles`.

[0.1.0]: https://github.com/vehiclesdb/vehiclesdb-python/releases/tag/v0.1.0
