# Changelog

All notable changes to `vehiclesdb` are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the package uses
[Semantic Versioning](https://semver.org/). While the version is 0.x, a minor
release may change the API.

## [0.1.0] - 2026-11-09

First public release.

### Added

- `VehiclesDB` client, with zero required dependencies, Python >= 3.9 support
  and inline type annotations (`py.typed`).
- **Dataset mode** (default, no key): `makes()`, `models()`, `model()`,
  `resolve()`, `model_match()`, `search()` and `dataset_version`, answered from
  the published CC-BY dataset on jsDelivr. Releases can be pinned with
  `version=`. The dataset is fetched lazily and memoized.
- **API mode**: `images()` for `GET /v1/vehicles/{kind}/{make}/{model}/images`,
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
