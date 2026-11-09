"""Opt-in: run the client against a FULL published release, not the fixture.

    VDB_DATA_REPO=../vehiclesdb python -m pytest tests

Why this exists on top of the fixture suite: `fixtures/` is 12 makes and
289 models, capped by `tools/make_fixtures.py`. Passing against it proves
the logic; it does not prove the client survives the real thing — 1,111 makes,
15,677 models, six kinds, models whose names collide across makes, and a
`dist/vehicles.json` two orders of magnitude larger. This test points the same
transport seam at a real data-repo checkout on disk.

Still offline: it reads local files, never the CDN.

It SKIPS (loudly, naming the path it wanted) when no checkout is present, which
is the correct behaviour for a repo that does not vendor a 4.9 MB dataset — a
test that silently passes because it found nothing to test is worse than one
that is not there.
"""

import json
import os
import unittest

from helpers import PACKAGE_ROOT  # noqa: F401  (puts src/ on sys.path)

from vehiclesdb import VehiclesDB  # noqa: E402

# Defaults to a checkout of github.com/vehiclesdb/vehiclesdb next to this
# repo; override with VDB_DATA_REPO when your checkout lives elsewhere.
DATA_REPO = os.path.expanduser(os.environ.get(
    "VDB_DATA_REPO", os.path.join(os.path.dirname(PACKAGE_ROOT), "vehiclesdb")))
DIST_PATH = os.path.join(DATA_REPO, "dist", "vehicles.json")
MANIFEST_PATH = os.path.join(DATA_REPO, "manifest.json")

BASE = "https://cdn.jsdelivr.net/gh/vehiclesdb/vehiclesdb@latest"


def local_transport(url, headers=None):
    """Serve the CDN layout out of a data-repo checkout.

    The client builds `<base>/dist/vehicles.json` and
    `<base>/catalog/<kind>/models.json`; a data-repo checkout has exactly those
    paths at its root, so the mapping is a prefix strip and nothing else.
    """
    if not url.startswith(BASE + "/"):
        raise AssertionError("unexpected URL %r — this test must never leave the disk" % url)
    path = os.path.join(DATA_REPO, url[len(BASE) + 1:])
    with open(path, "rb") as fh:
        return (200, fh.read())


@unittest.skipUnless(
    os.path.exists(DIST_PATH),
    "no published release at %s — set VDB_DATA_REPO to a data-repo checkout to run "
    "the full-release checks (SKIPPED, not silently passed)" % DIST_PATH,
)
class FullReleaseTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = VehiclesDB(transport=local_transport)
        with open(MANIFEST_PATH, encoding="utf-8") as fh:
            cls.manifest = json.load(fh)

    def test_make_counts_match_the_manifest(self):
        # manifest.json is emitted by the release build; if the client's own view of
        # the release disagrees with it, one of the two is reading it wrong.
        for kind, counts in self.manifest["kinds"].items():
            self.assertEqual(
                len(self.db.makes(kind=kind)), counts["makes"],
                "make count for kind %r disagrees with manifest.json" % kind,
            )

    def test_model_counts_match_the_manifest(self):
        for kind, counts in self.manifest["kinds"].items():
            total = sum(len(self.db.models(m.slug, kind=kind)) for m in self.db.makes(kind=kind))
            self.assertEqual(
                total, counts["models"],
                "model count for kind %r disagrees with manifest.json" % kind,
            )

    def test_resolve_ladder_on_real_data(self):
        # One case per rung, against the whole catalog rather than 289 models —
        # the interesting risk is a rung firing on the WRONG record once there
        # are 15,677 of them to collide with.
        cases = [
            ("car/volkswagen/golf", "car/volkswagen/golf", "exact"),
            ("Citroën C3", "car/citroen/c3", "fold"),
            ("car/alfa-romeo/1750gtv", "car/alfa-romeo/1750-gtv", "former_id"),
        ]
        for query, expected_id, expected_rung in cases:
            hit = self.db.resolve(query)
            self.assertIsNotNone(hit, "resolve(%r) found nothing in the full release" % query)
            self.assertEqual(hit.id, expected_id, "resolve(%r)" % query)
            self.assertEqual(hit.matched_on, expected_rung, "resolve(%r) rung" % query)

    def test_resolve_misses_are_still_none(self):
        # A bigger corpus means more chances to match something by accident.
        self.assertIsNone(self.db.resolve("delorean dmc-12"))
        for query in ("nope nope", "qqqqq zzzzz"):
            self.assertIsNone(self.db.resolve(query), "resolve(%r) invented a match" % query)

    def test_bare_model_names_never_resolve(self):
        # Contract rule 2. These are exact published names; naming the make is
        # what turns them into an answer.
        for query in ("golf", "Sprinter", "duster"):
            self.assertIsNone(self.db.resolve(query), "resolve(%r) guessed" % query)
        self.assertEqual(self.db.resolve("vw golf").id, "car/volkswagen/golf")

    def test_rung_3_ambiguity_is_computed_from_THIS_corpus(self):
        # The counterpart of tests/test_client.py's fixture assertions, and the
        # reason both exist: rung 3's refusal is a computation over whatever
        # corpus is loaded, never a hardcoded string.
        #
        # Here the full release DOES carry car/volkswagen/rabbit, so "Rabbit"
        # matches two records — a published alias of the Golf and that record's
        # own name — and refuses. Against fixtures/, where the 30-model cap
        # drops the rabbit record, the SAME code resolves it to the Golf.
        # If you are here because the fixture test asserts `alias` and this one
        # asserts null: that is the design, not a contradiction.
        self.assertIsNotNone(self.db.model("car/volkswagen/rabbit"))
        self.assertIn("Rabbit", self.db.model("car/volkswagen/golf").aliases)
        self.assertIsNone(self.db.resolve("Rabbit"))

        # Same corpus difference, seen from rung 2: with a make named, the
        # rabbit record's own NAME claims the remainder before rung 3 can offer
        # the Golf's alias.
        hit = self.db.resolve("vw rabbit")
        self.assertEqual(hit.id, "car/volkswagen/rabbit")
        self.assertEqual(hit.matched_on, "fold")

        # Kind variants of the same alias target resolve using the SDK tie-break.
        self.assertFalse(self.db.resolve("Tin Lizzie").ambiguous)

    def test_full_former_id_precedes_names(self):
        hit = self.db.resolve("car/alfa-romeo/1750gtv")
        self.assertEqual(hit.method, "former_id")

    def test_full_record_round_trip(self):
        # dist/ gives the compact record; catalog/ gives sources + per-country
        # popularity. The id must survive the hop between the two files.
        model = self.db.model("car/ford/mustang-mach-e")
        self.assertIsNotNone(model)
        self.assertEqual(model.name, "Mustang Mach-E")
        self.assertIn("de", model.availability)  # KBA FZ 10 evidences it in Germany


if __name__ == "__main__":
    unittest.main()
