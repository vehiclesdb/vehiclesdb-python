#!/usr/bin/env python3
"""Cut the SDK test fixtures out of a real published VehiclesDB release.

Why a generator and not hand-written JSON: a hand-written fixture drifts from
the real schema the moment a release adds a new field, and then both SDKs
pass their tests against a shape that no longer exists on the CDN. This script
takes a REAL `dist/vehicles.json` + `catalog/**` from a data-repo checkout and
slices out a handful of makes verbatim — same keys, same nesting, same value
types — so the fixtures can only ever be a subset of reality, never a fiction.

It needs only a checkout of the public dataset repo, at the release tag you
want to cut from:

    git clone https://github.com/vehiclesdb/vehiclesdb ../vehiclesdb
    git -C ../vehiclesdb checkout v2026.07.6   # the release the fixtures pin
    python3 tools/make_fixtures.py --data-repo ../vehiclesdb

The JS SDK (vehiclesdb/vehiclesdb-js) and the Python SDK
(vehiclesdb/vehiclesdb-python) each carry a copy of `fixtures/`, and the two
copies must stay byte-identical: identical bytes in, identical answers
expected out. Regenerate in one repo, copy the directory to the other, and run
`tools/parity_check.sh`.

Stdlib only, Python 3.8+ (macOS system python is 3.9) — the SDKs' own floor.
"""

import argparse
import json
import os
import sys

# The fixture makes, chosen so every code path the SDKs claim to handle has at
# least one real record behind it. Do not trim this list without re-reading the
# reason column — each one is load-bearing for a test.
FIXTURE_MAKES = [
    "volkswagen",     # make aliases ("VW"), the resolve() headline case
    "bmw",            # make aliases; a make whose models are alphanumeric series
    "alfa-romeo",     # make aliases + model former_ids (the 1750 GTV rename chain)
    "citroen",        # ASCII slug for a diacritic display name ("Citroën")
    "mercedes-benz",  # hyphenated make slug; kind-spanning (car/van/truck/bus)
    "seat",           # a make whose slug is an English word — search-ranking trap
    "toyota",         # high model count, multi-kind
    "ford",           # multi-kind (car/van/truck), the CarQuery benchmark make
    "tesla",          # tiny make: exercises "few models" edges
    "aixam",          # multi-kind micro-make (car/moped/van): kind filtering
    "renault",        # top-of-market EU make, models with former_ids
    "dacia",          # the make that shares a corporate parent with renault
]


# Models kept per make. The full slice of these 12 makes is ~3.1 MB, which is
# not a thing to commit to a repo for a unit test; capping keeps the fixtures
# under half a megabyte. The cap is NOT a random head() — see pick_models().
MODELS_PER_MAKE = 30


def pick_models(models):
    """Choose which of a make's models survive the cap.

    Priority order, because each tier is something a test needs to exist:
      1. models carrying `former_ids`  — the id-migration path in resolve()
      2. models carrying `aliases`     — the alias path in resolve()/search()
      3. everything else by popularity (global_decile asc, nil last), so the
         survivors are the models a real integration would actually hit.
    Ties break on slug so the fixture is byte-stable across regenerations.
    """
    def rank(m):
        return (
            0 if m.get("former_ids") else 1,
            0 if m.get("aliases") else 1,
            m.get("global_decile") if m.get("global_decile") is not None else 99,
            m["slug"],
        )

    kept = sorted(models, key=rank)[:MODELS_PER_MAKE]
    # Emit in the release's own order (alphabetical by slug) so the fixture
    # reads like a real file rather than like a ranking.
    return sorted(kept, key=lambda m: (m["kind"], m["slug"]))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-repo", required=True,
                    help="path to a vehiclesdb data-repo checkout (needs dist/ and catalog/)")
    ap.add_argument("--out", default=os.path.join(os.path.dirname(__file__), "..", "fixtures"))
    args = ap.parse_args()

    data_repo = os.path.expanduser(args.data_repo)
    out = os.path.abspath(os.path.expanduser(args.out))

    src_dist = os.path.join(data_repo, "dist", "vehicles.json")
    src_manifest = os.path.join(data_repo, "manifest.json")
    if not os.path.exists(src_dist):
        sys.exit("no %s — point --data-repo at a built data-repo checkout" % src_dist)

    with open(src_dist, encoding="utf-8") as fh:
        dist = json.load(fh)
    with open(src_manifest, encoding="utf-8") as fh:
        manifest = json.load(fh)

    wanted = set(FIXTURE_MAKES)
    makes = [m for m in dist["makes"] if m["slug"] in wanted]
    missing = wanted - {m["slug"] for m in makes}
    if missing:
        sys.exit("these fixture makes are not in the release: %s" % sorted(missing))

    fixture_dist = {
        "version": dist["version"],
        "schema_version": dist["schema_version"],
        "region": dist["region"],
        "kinds": dist["kinds"],
        "source": dist["source"],
        "license": dist["license"],
        "makes": [
            {k: (pick_models(v) if k == "models" else v) for k, v in make.items()}
            for make in makes
        ],
    }
    # The exact id set that survived the cap. The catalog slices below are
    # filtered to it so the two files can never disagree about what exists —
    # a test that resolves an id from dist/ and then asks for its full record
    # must not fall off a cliff.
    kept_ids = {
        "%s/%s/%s" % (mo["kind"], make["slug"], mo["slug"])
        for make in fixture_dist["makes"] for mo in make["models"]
    }

    os.makedirs(os.path.join(out, "dist"), exist_ok=True)
    write(os.path.join(out, "dist", "vehicles.json"), fixture_dist)

    # Per-kind catalog slices — the SDKs' "full record" path (sources, xrefs,
    # per-country popularity) reads these, exactly like the CDN layout.
    kinds_present = set()
    for kind in dist["kinds"]:
        cat_makes_path = os.path.join(data_repo, "catalog", kind, "makes.json")
        cat_models_path = os.path.join(data_repo, "catalog", kind, "models.json")
        if not (os.path.exists(cat_makes_path) and os.path.exists(cat_models_path)):
            continue
        with open(cat_makes_path, encoding="utf-8") as fh:
            cat_makes = [m for m in json.load(fh) if m["id"] in wanted]
        with open(cat_models_path, encoding="utf-8") as fh:
            cat_models = [
                m for m in json.load(fh)
                # catalog ids are kind-scoped by their FILE, so the canonical
                # `kind/make/model` id has to be rebuilt to compare with dist/.
                if "%s/%s/%s" % (kind, m["make_id"], m["slug"]) in kept_ids
            ]
        if not cat_models:
            continue
        kinds_present.add(kind)
        os.makedirs(os.path.join(out, "catalog", kind), exist_ok=True)
        write(os.path.join(out, "catalog", kind, "makes.json"), cat_makes)
        write(os.path.join(out, "catalog", kind, "models.json"), cat_models)

    fixture_manifest = {
        "version": manifest["version"],
        "edition": manifest["edition"],
        "built_at": manifest["built_at"],
        "schema_version": manifest["schema_version"],
        "dist_schema_version": manifest["dist_schema_version"],
        "license": manifest["license"],
        "homepage": manifest["homepage"],
        "kinds": {k: v for k, v in manifest["kinds"].items() if k in kinds_present},
        "countries": manifest["countries"],
        "catalog": {k: v for k, v in manifest["catalog"].items() if k in kinds_present},
        "dist": {"vehicles": "dist/vehicles.json"},
        "_fixture": (
            "SUBSET of release %s, cut by tools/make_fixtures.py for offline "
            "SDK tests. Not a release artifact; never publish or serve this."
        ) % manifest["version"],
    }
    write(os.path.join(out, "manifest.json"), fixture_manifest)

    n_models = sum(len(m["models"]) for m in fixture_dist["makes"])
    print("fixtures written to %s" % out)
    print("  release        %s (built_at %s)" % (manifest["version"], manifest["built_at"]))
    print("  makes          %d" % len(makes))
    print("  models         %d" % n_models)
    print("  catalog kinds  %s" % ", ".join(sorted(kinds_present)))


def write(path, obj):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=2, sort_keys=False)
        fh.write("\n")


if __name__ == "__main__":
    main()
