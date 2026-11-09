"""Offline tests for the vehiclesdb package.

    /usr/bin/python3 -m unittest discover -s tests -v

Every expected value in here is a fact about the real fixture (a verbatim
subset of release 2026.07.6, cut by tools/make_fixtures.py), not a number
someone liked. Where a count is asserted, it is also cross-checked against the
fixture file itself, so regenerating the fixtures fails the test loudly rather
than leaving a stale constant behind.
"""

import sys
import unittest

from helpers import (  # noqa: E402  (helpers puts src/ on sys.path)
    API_BASE_URL,
    DATASET_BASE_URL,
    FixtureNotFound,
    FixtureTransport,
    OfflineTestCase,
    StubTransport,
    load_fixture,
)

from vehiclesdb import (  # noqa: E402
    ATTRIBUTION_TEXT,
    MATCH_CONFIDENCE,
    Make,
    MissingApiKeyError,
    Model,
    Resolution,
    VehiclesDB,
    VehiclesDBApiError,
    httpx_transport,
)
from vehiclesdb._normalize import fold, slugify  # noqa: E402

DIST = load_fixture("dist", "vehicles.json")
FIXTURE_MAKES = {m["slug"]: m for m in DIST["makes"]}


def fixture_models(make_slug, kind=None):
    models = FIXTURE_MAKES[make_slug]["models"]
    return [m for m in models if kind is None or m["kind"] == kind]


# ---------------------------------------------------------------------------
# normalization — the parity surface the JS SDK has to reproduce
# ---------------------------------------------------------------------------

class NormalizeTest(unittest.TestCase):
    def test_fold_strips_diacritics_and_collapses_punctuation(self):
        self.assertEqual(fold("Citroën"), "citroen")
        self.assertEqual(fold("Mercedes-Benz"), "mercedes benz")
        self.assertEqual(fold("C3 Aircross 1.2"), "c3 aircross 1 2")
        self.assertEqual(fold("R80G/S"), "r80g s")
        # A model name and its slug must fold to the SAME key — that is what
        # lets resolve() rung 5 match either.
        self.assertEqual(fold("159 SW"), fold("159-sw"))
        self.assertEqual(fold("Id. Buzz"), fold("id-buzz"))

    def test_fold_is_ascii_with_compatibility_normalization(self):
        # Native-script aliases use raw equality, outside the ASCII fold.
        self.assertEqual(fold("丰田"), "")
        self.assertEqual(fold("ﬁ ①"), "fi 1")

    def test_slugify_matches_published_slug_shape(self):
        self.assertEqual(slugify("1750gtv"), "1750gtv")
        self.assertEqual(slugify("159 SW"), "159-sw")
        self.assertEqual(slugify("Citroën C3"), "citroen-c3")


# ---------------------------------------------------------------------------
# makes()
# ---------------------------------------------------------------------------

class MakesTest(OfflineTestCase):
    def test_returns_every_make_unioned_across_kinds(self):
        makes = self.db.makes()
        self.assertEqual(len(makes), len(DIST["makes"]))
        self.assertEqual(len(makes), 12)
        self.assertTrue(all(isinstance(m, Make) for m in makes))
        # Sorted by slug, deterministically, whatever order the file used.
        self.assertEqual([m.slug for m in makes], sorted(FIXTURE_MAKES))

    def test_multi_kind_make_appears_once_carrying_all_its_kinds(self):
        aixam = next(m for m in self.db.makes() if m.slug == "aixam")
        self.assertEqual(aixam.kinds, ["car", "moped", "van"])
        ford = next(m for m in self.db.makes() if m.slug == "ford")
        self.assertEqual(ford.kinds, ["car", "van", "truck", "bus"])

    def test_kind_filters_on_the_published_kinds_list(self):
        for kind, expected in [
            ("car", 12),
            ("van", 9),
            ("truck", 6),
            ("bus", 6),
            ("moped", 4),
            ("motorcycle", 2),
        ]:
            from_fixture = sum(1 for m in DIST["makes"] if kind in m["kinds"])
            self.assertEqual(from_fixture, expected, "fixture changed for kind=%s" % kind)
            self.assertEqual(len(self.db.makes(kind=kind)), expected, kind)

        self.assertEqual(
            [m.slug for m in self.db.makes(kind="motorcycle")], ["bmw", "renault"]
        )

    def test_published_make_aliases_survive_and_absence_is_none(self):
        vw = next(m for m in self.db.makes() if m.slug == "volkswagen")
        self.assertEqual(vw.aliases, ["VW", "Vdub"])
        # Citroën has no curated make aliases: absent means "not curated yet",
        # never [] (SCHEMA.md, the absence rule).
        citroen = next(m for m in self.db.makes() if m.slug == "citroen")
        self.assertIsNone(citroen.aliases)
        self.assertNotIn("aliases", citroen.to_dict())

    def test_make_id_equals_slug(self):
        # dist/ carries no make id; catalog/{kind}/makes.json does, and there
        # id == slug for every make in the release.
        catalog_makes = load_fixture("catalog", "car", "makes.json")
        self.assertTrue(all(m["id"] == m["slug"] for m in catalog_makes))
        self.assertTrue(all(m.id == m.slug for m in self.db.makes()))


# ---------------------------------------------------------------------------
# models()
# ---------------------------------------------------------------------------

class ModelsTest(OfflineTestCase):
    def test_by_slug_display_name_and_alias_are_the_same_call(self):
        by_slug = self.db.models("volkswagen")
        self.assertEqual(len(by_slug), len(fixture_models("volkswagen")))
        self.assertEqual(len(by_slug), 30)
        for spelling in ["Volkswagen", "VW", "vw", "vdub"]:
            self.assertEqual(
                [m.id for m in self.db.models(spelling)],
                [m.id for m in by_slug],
                spelling,
            )

    def test_kind_filter(self):
        cars = self.db.models("VW", kind="car")
        self.assertEqual(len(cars), len(fixture_models("volkswagen", "car")))
        self.assertEqual(len(cars), 22)
        self.assertTrue(all(m.kind == "car" for m in cars))
        self.assertIn("car/volkswagen/golf", [m.id for m in cars])

    def test_body_type_filter_uses_the_dist_primary_body_type(self):
        suvs = self.db.models("VW", kind="car", body_type="suv")
        self.assertEqual(
            {m.id for m in suvs},
            {
                m["kind"] + "/volkswagen/" + m["slug"]
                for m in fixture_models("volkswagen", "car")
                if m.get("body_type") == "suv"
            },
        )
        self.assertIn("car/volkswagen/tiguan", [m.id for m in suvs])

    def test_hyphenated_and_spaced_make_names_both_resolve(self):
        self.assertEqual(
            [m.id for m in self.db.models("mercedes benz")],
            [m.id for m in self.db.models("Mercedes-Benz")],
        )
        # "Merc" is a published alias.
        self.assertEqual(
            [m.id for m in self.db.models("merc")],
            [m.id for m in self.db.models("mercedes-benz")],
        )

    def test_diacritic_make_name_resolves_from_ascii(self):
        self.assertEqual(
            [m.id for m in self.db.models("citroen")],
            [m.id for m in self.db.models("Citroën")],
        )

    def test_unknown_make_returns_empty_list_and_never_raises(self):
        # Same promise as the Ruby gem: a picker fed user input cannot crash.
        self.assertEqual(self.db.models("DeLorean"), [])
        self.assertEqual(self.db.models(""), [])
        self.assertEqual(self.db.models("   "), [])

    def test_models_returns_the_lean_projection_without_a_catalog_fetch(self):
        golf = next(m for m in self.db.models("VW", kind="car") if m.slug == "golf")
        self.assertEqual(golf.body_type, "hatchback")
        self.assertEqual(golf.global_decile, 2)
        self.assertEqual(golf.aliases, ["Rabbit"])
        self.assertIsNone(golf.popularity)  # depth lives in catalog/, not fetched
        self.assertIsNone(golf.sources)
        self.assertEqual(self.transport.urls, ["%s/dist/vehicles.json" % DATASET_BASE_URL])


# ---------------------------------------------------------------------------
# model()
# ---------------------------------------------------------------------------

class ModelTest(OfflineTestCase):
    def test_full_id_and_three_arg_form_agree(self):
        by_id = self.db.model("car/volkswagen/golf")
        by_parts = self.db.model("car", "volkswagen", "golf")
        self.assertIsInstance(by_id, Model)
        self.assertEqual(by_id, by_parts)
        self.assertEqual(by_id.id, "car/volkswagen/golf")
        self.assertEqual(by_id.make_name, "Volkswagen")
        self.assertEqual(by_id.full_name, "Volkswagen Golf")

    def test_full_record_merges_the_per_kind_catalog(self):
        golf = self.db.model("car/volkswagen/golf")
        catalog = {m["id"]: m for m in load_fixture("catalog", "car", "models.json")}
        record = catalog["volkswagen/golf"]
        # The catalog's own id is `make/model` — kind-scoped by the file — and
        # we rebuild the three-part canonical id.
        self.assertEqual(record["id"], "volkswagen/golf")
        self.assertEqual(golf.id, "car/volkswagen/golf")
        self.assertEqual(golf.body_types, record["body_types"])
        self.assertEqual(golf.popularity, record["popularity"])
        self.assertEqual(golf.sources, record["sources"])
        self.assertEqual(golf.global_decile, record["popularity"]["global_decile"])
        # availability is bare country codes from EITHER projection...
        self.assertEqual(golf.availability, [r["country"] for r in record["availability"]])
        self.assertTrue(all(isinstance(c, str) for c in golf.availability))
        # ...and the evidence rows are still reachable.
        self.assertEqual(golf.raw["availability"], record["availability"])
        self.assertTrue(golf.available_in("nl"))

    def test_former_id_still_resolves(self):
        # The "old ids keep working" promise, against a real published rename.
        published = next(m for m in fixture_models("alfa-romeo") if m["slug"] == "1750-gtv")
        self.assertIn("car/alfa-romeo/1750gtv", published["former_ids"])
        moved = self.db.model("car/alfa-romeo/1750gtv")
        self.assertIsNotNone(moved)
        self.assertEqual(moved.id, "car/alfa-romeo/1750-gtv")
        self.assertEqual(moved.name, "1750 GTV")

    def test_id_is_case_insensitive_and_slash_tolerant(self):
        self.assertEqual(self.db.model("Car/Volkswagen/Golf").id, "car/volkswagen/golf")
        self.assertEqual(self.db.model("/car/volkswagen/golf/").id, "car/volkswagen/golf")

    def test_unknown_id_returns_none(self):
        self.assertIsNone(self.db.model("car/volkswagen/delorean"))
        self.assertIsNone(self.db.model("car", "nosuchmake", "nosuchmodel"))

    def test_bad_arity_is_a_type_error(self):
        with self.assertRaises(TypeError):
            self.db.model("car", "volkswagen")

    def test_absence_rule_in_to_dict(self):
        # Mopeds carry no body types (SCHEMA.md: "no honest vocabulary
        # derivable from registers"), so the key must be ABSENT, not null.
        moped = self.db.model("moped/aixam/k2")
        self.assertIsNone(moped.body_types)
        payload = moped.to_dict()
        self.assertNotIn("body_types", payload)
        self.assertNotIn("body_type", payload)
        self.assertEqual(payload["id"], "moped/aixam/k2")


# ---------------------------------------------------------------------------
# resolve() — one test per rung, reporting matched_on
# ---------------------------------------------------------------------------

class ResolveLadderTest(OfflineTestCase):
    def assertResolves(self, query, expected_id, matched_on, **kwargs):
        result = self.db.resolve(query, **kwargs)
        self.assertIsInstance(result, Resolution, "%r did not resolve" % query)
        self.assertEqual(result.id, expected_id, query)
        self.assertEqual(result.matched_on, matched_on, query)
        self.assertEqual(result.confidence, .90 if query in ("Renault Duster", "Renault Logan", "Rabbit", "Tin Lizzie") else MATCH_CONFIDENCE[matched_on])
        self.assertEqual(result.source, "dataset")
        return result

    def test_rung_1_exact_canonical_id(self):
        result = self.assertResolves("car/volkswagen/golf", "car/volkswagen/golf", "exact")
        self.assertEqual(result.make, "Volkswagen")
        self.assertEqual(result.model, "Golf")
        self.assertEqual(result.kind, "car")

    def test_rung_2_exact_name_or_slug_within_a_resolved_make(self):
        self.assertResolves("citroen c3", "car/citroen/c3", "fold")
        self.assertResolves("Citroën C3", "car/citroen/c3", "fold")
        self.assertResolves("VW Golf", "car/volkswagen/golf", "fold")
        self.assertResolves("alfa romeo 159-sw", "car/alfa-romeo/159-sw", "fold")

    def test_citroen_spellings_agree(self):
        # The headline diacritic case, stated as the contract states it: the
        # ASCII spelling and the published one land on the same id.
        self.assertEqual(
            self.db.resolve("citroen c3").id,
            self.db.resolve("Citroën C3").id,
        )

    def test_rung_2_scopes_to_the_resolved_make(self):
        # "C3" is a Citroën car AND an Aixam moped. Naming the make disambiguates.
        self.assertResolves("citroen c3", "car/citroen/c3", "fold")
        self.assertResolves("aixam c3", "moped/aixam/c3", "fold")

    def test_rung_3_make_scoped_published_model_alias(self):
        # "Rabbit" is a published alias of the Golf and matches no Volkswagen
        # NAME in this corpus, so rung 2 passes and rung 3 answers.
        self.assertResolves("vw rabbit", "car/volkswagen/golf", "alias")
        self.assertResolves("dacia Renault Duster", "car/dacia/duster", "alias")
        self.assertResolves("vw käfer", "car/volkswagen/beetle", "alias")

    def test_rung_2_folds_so_an_accented_alias_is_not_needed(self):
        # Rung 2 compares after the SAME fold as rung 5 (contract rule 4), so
        # "León" folds onto the name "Leon" and this is a rung-2 hit. The
        # published alias "León" on that record is therefore never the thing
        # that answers here — which is correct: a nameplate outranks a spelling
        # variant of itself.
        self.assertResolves("SEAT León", "car/seat/leon", "fold")
        self.assertResolves("seat leon", "car/seat/leon", "fold")

    def test_rung_3_is_make_independent_when_the_whole_query_is_an_alias(self):
        # Dacia publishes "Renault Duster"/"Renault Logan"/"Renault Sandero"
        # because Dacia sells as Renault in several markets. A user typing one
        # in full has named exactly one record, and refusing it would throw away
        # the entire reason the alias field exists.
        #
        # NOTE this is corpus-dependent by design: the fixture has no
        # `car/renault/duster`, so no Renault NAME claims the remainder and the
        # alias answers. In the full release that record DOES exist, so rung 2
        # fires first and the answer is `car/renault/duster` [slug]. Same rule,
        # different corpus, different (correct) answer.
        self.assertResolves("Renault Duster", "car/dacia/duster", "alias")
        self.assertResolves("Renault Logan", "car/dacia/logan", "alias")

    def test_alias_kind_variants_are_one_record(self):
        # Kind variants of the same make/model are one whole-text alias target.
        published = [
            "%s/ford/%s" % (m["kind"], m["slug"])
            for m in fixture_models("ford")
            if "Tin Lizzie" in (m.get("aliases") or [])
        ]
        self.assertEqual(published, ["car/ford/model-t", "van/ford/model-t"])
        self.assertResolves("Tin Lizzie", "car/ford/model-t", "alias")
        # Narrowing the corpus with kind= selects the requested variant,
        # while the default uses the SDK tie-break.
        self.assertResolves("Tin Lizzie", "car/ford/model-t", "alias", kind="car")

    def test_rung_3_ambiguity_counts_names_as_well_as_aliases(self):
        # A record whose own NAME equals the query is an ambiguity signal even
        # though a bare name can never resolve on its own. In the full release
        # this is what makes "Rabbit" null (alias of car/volkswagen/golf, name
        # of car/volkswagen/rabbit). The fixture's 30-model cap drops that
        # second record, so here "Rabbit" is unambiguous and resolves.
        #
        # DO NOT "fix" this to null — the corpus is the input to the rule.
        # tests/test_full_release.py asserts the null against the real release.
        self.assertNotIn("rabbit", [m.slug for m in self.db.models("volkswagen")])
        self.assertResolves("Rabbit", "car/volkswagen/golf", "alias")

    def test_rung_4_former_ids_full_id_form(self):
        self.assertResolves("car/alfa-romeo/1750gtv", "car/alfa-romeo/1750-gtv", "former_id")

    def test_human_former_slug_can_match_by_spacing(self):
        # This spelling matches the current name by spacing, not the former-id rung.
        self.assertResolves("alfa romeo 1750gtv", "car/alfa-romeo/1750-gtv", "fold")

    def test_rung_4_loses_to_a_current_id(self):
        # A current id always wins over anyone's former id (rung 1 before 4).
        self.assertResolves("car/alfa-romeo/gtv", "car/alfa-romeo/gtv", "exact")

    def test_trailing_trim_requires_a_published_form(self):
        for query in ['VW Golf 1.9 TDI', 'citroen c3 aircross 1.2', 'ford mustang mach-e gt']:
            self.assertIsNone(self.db.resolve(query))

    def test_merc_c_class_is_rung_2_not_rung_5(self):
        # Contract rule 4, and the case that forced it: "Merc" is a PUBLISHED
        # make alias, and the remainder "c class" folds exactly onto the name
        # "C-Class". The caller named one model exactly, just with a space where
        # the catalog has a hyphen — so this is rung 2, not a junk-tolerant
        # rung-5 guess. Rung 5 stays the only rung that accepts trailing noise.
        self.assertResolves("merc c class", "car/mercedes-benz/c-class", "fold")

    def test_a_miss_is_none_not_a_guess(self):
        # Inputs outside the conservative typo limits remain misses.
        self.assertIsNone(self.db.resolve("nope nope"))
        self.assertIsNone(self.db.resolve("delorean dmc-12"))
        self.assertIsNone(self.db.resolve(""))
        self.assertIsNone(self.db.resolve("   "))

    def test_a_bare_make_is_not_a_model_resolution(self):
        self.assertIsNone(self.db.resolve("volkswagen"))

    def test_a_bare_model_name_never_resolves(self):
        # Contract rule 2. "golf" is the exact name of car/volkswagen/golf and
        # nothing else in this corpus, and it STILL refuses: an exact name is
        # only an ambiguity signal, never an answer on its own, because picking
        # one nameplate out of 15,677 on a bare fragment is a guess dressed as
        # an answer. Name the make ("vw golf") and it resolves at rung 2.
        self.assertEqual([m.id for m in self.db.search("golf")], ["car/volkswagen/golf"])
        self.assertIsNone(self.db.resolve("golf"))
        self.assertIsNone(self.db.resolve("Sprinter"))
        self.assertResolves("vw golf", "car/volkswagen/golf", "fold")

    def test_only_published_make_aliases_count(self):
        # Contract rule 3. Mercedes-Benz publishes ["Merc", "Benz", "MB"] —
        # NOT "Mercedes". There is deliberately no "the query starts with part
        # of the make's name" fallback: that is what once turned this query into
        # a junk catalog record.
        mercedes = next(m for m in self.db.makes() if m.slug == "mercedes-benz")
        self.assertEqual(mercedes.aliases, ["Merc", "Benz", "MB"])
        self.assertNotIn("Mercedes", mercedes.aliases)
        self.assertIsNone(self.db.resolve("mercedes c class"))
        # The published spellings all work.
        for spelling in ["merc", "benz", "mb", "mercedes-benz", "mercedes benz"]:
            self.assertEqual(
                self.db.resolve("%s c class" % spelling).id,
                "car/mercedes-benz/c-class",
                spelling,
            )

    def test_kind_narrows_a_genuinely_ambiguous_query(self):
        # Aixam publishes a "Mega" as a car, a moped AND a van.
        self.assertResolves("aixam mega", "van/aixam/mega", "fold")  # decile 4 wins
        self.assertResolves("aixam mega", "car/aixam/mega", "fold", kind="car")
        self.assertResolves("aixam mega", "moped/aixam/mega", "fold", kind="moped")

    def test_country_narrows_on_published_availability_evidence(self):
        # Mercedes-Benz ships a "Sprinter" as a van, a truck and a bus, and the
        # three are evidenced in different countries. `country=` filters on the
        # published availability, so it can pick out a kind the bare query
        # cannot.
        sprinters = {
            m.kind: m
            for m in self.db.models("mercedes-benz")
            if m.slug == "sprinter"
        }
        self.assertEqual(sorted(sprinters), ["bus", "truck", "van"])

        exclusive = {
            kind: set(model.availability)
            - set().union(*[set(o.availability) for k, o in sprinters.items() if k != kind])
            for kind, model in sprinters.items()
        }
        for kind, only_here in exclusive.items():
            if not only_here:
                continue
            country = sorted(only_here)[0]
            picked = self.db.resolve("mercedes benz sprinter", country=country)
            self.assertEqual(picked.kind, kind, "country=%s should force kind=%s" % (country, kind))

        # A country nobody is evidenced in is a miss, not a fallback.
        self.assertIsNone(self.db.resolve("mercedes benz sprinter", country="jp"))

    def test_resolution_to_dict_carries_the_contract_fields(self):
        payload = self.db.resolve("VW Golf").to_dict()
        self.assertEqual(
            sorted(k for k in payload if k in {"confidence", "id", "kind", "make", "matched_on", "model", "source"}),
            ["confidence", "id", "kind", "make", "matched_on", "model", "source"],
        )
        self.assertEqual(payload["id"], "car/volkswagen/golf")
        self.assertEqual(payload["source"], "dataset")


# ---------------------------------------------------------------------------
# search()
# ---------------------------------------------------------------------------

class SearchTest(OfflineTestCase):
    def test_exact_ordering_for_a_multi_hit_query(self):
        # Three makes-worth of "Sprinter" at two deciles: 1 (bus), 1 (truck),
        # 2 (van). Tier is equal, so decile then name then id decides.
        self.assertEqual(
            [m.id for m in self.db.search("sprinter")],
            [
                "bus/mercedes-benz/sprinter",
                "truck/mercedes-benz/sprinter",
                "van/mercedes-benz/sprinter",
            ],
        )

    def test_tier_beats_popularity(self):
        # "C3 Aircross" (decile 4) is a PREFIX hit, so it ranks behind both
        # exact-name hits even though it outranks the Aixam moped C3 (decile 7).
        self.assertEqual(
            [m.id for m in self.db.search("c3")],
            ["car/citroen/c3", "moped/aixam/c3", "car/citroen/c3-aircross"],
        )

    def test_prefix_tier_ordering(self):
        self.assertEqual(
            [m.id for m in self.db.search("model")],
            [
                "car/tesla/model-3",
                "car/tesla/model-y",
                "car/ford/model-t",
                "car/tesla/model-s",
                "car/tesla/model-x",
                "van/ford/model-t",
            ],
        )

    def test_limit_is_honoured(self):
        self.assertEqual(
            [m.id for m in self.db.search("model", limit=3)],
            ["car/tesla/model-3", "car/tesla/model-y", "car/ford/model-t"],
        )
        self.assertEqual(self.db.search("model", limit=0), [])
        self.assertEqual(len(self.db.search("model", limit=100)), 6)

    def test_kind_filter(self):
        self.assertEqual([m.id for m in self.db.search("mega", kind="moped")], ["moped/aixam/mega"])
        # The three exact "Mega" hits (deciles 4/8/9) come first, and Renault's
        # "Megane" follows as a prefix hit — tier before popularity, again.
        self.assertEqual(
            [m.id for m in self.db.search("mega")],
            [
                "van/aixam/mega",
                "car/aixam/mega",
                "moped/aixam/mega",
                "car/renault/megane",
            ],
        )

    def test_aliases_rank_below_every_name_hit(self):
        # "Rabbit" is a published alias of the Golf and matches no name.
        self.assertEqual([m.id for m in self.db.search("rabbit")], ["car/volkswagen/golf"])
        # A nickname never outranks a real name.
        ids = [m.id for m in self.db.search("duster")]
        self.assertEqual(ids[0], "car/dacia/duster")

    def test_search_folds_diacritics(self):
        self.assertEqual(
            [m.id for m in self.db.search("cordoba")],
            [m.id for m in self.db.search("Córdoba")],
        )

    def test_empty_query_returns_nothing(self):
        self.assertEqual(self.db.search(""), [])
        self.assertEqual(self.db.search("   "), [])


# ---------------------------------------------------------------------------
# images() — the one live /v1 endpoint
# ---------------------------------------------------------------------------

# Transcribed from the endpoint's documented response example
# (https://vehiclesdb.com/api).
IMAGE_200 = {
    "id": "car/renault/clio",
    "color": "blue",
    "requested_color": "blue",
    "palette": ["black", "blue", "grey", "red", "white"],
    "variants": {
        "sm": {"url": "https://vehiclesdb.com/rails/…/car-renault-clio-blue.png", "width": 320, "height": 180},
        "md": {"url": "https://vehiclesdb.com/rails/…/car-renault-clio-blue.png", "width": 640, "height": 360},
        "lg": {"url": "https://vehiclesdb.com/rails/…/car-renault-clio-blue.png", "width": 1280, "height": 720},
    },
    "format": "webp",
    "provenance": {"generated": True, "license_note": "Generated imagery for product use."},
}


class ImagesTest(unittest.TestCase):
    def client(self, transport, api_key="test-key"):
        return VehiclesDB(
            dataset_base_url=DATASET_BASE_URL,
            api_base_url=API_BASE_URL,
            api_key=api_key,
            transport=transport,
        )

    def test_raises_without_an_api_key_and_names_the_argument(self):
        transport = FixtureTransport()
        db = self.client(transport, api_key=None)
        with self.assertRaises(MissingApiKeyError) as caught:
            db.images("car/renault/clio", color="blue")
        self.assertEqual(caught.exception.argument, "api_key")
        self.assertEqual(caught.exception.method, "images")
        self.assertIn("api_key", str(caught.exception))
        # It must fail BEFORE any request — no key, no round trip.
        self.assertEqual(transport.calls, [])

    def test_sends_bearer_auth_to_the_documented_path(self):
        stub = StubTransport(200, IMAGE_200)
        payload = self.client(stub).images("car/renault/clio", color="blue")
        url, headers = stub.calls[0]
        self.assertEqual(url, "%s/v1/vehicles/car/renault/clio/images?color=blue" % API_BASE_URL)
        self.assertEqual(headers["Authorization"], "Bearer test-key")
        self.assertEqual(headers["Accept"], "application/json")
        self.assertTrue(headers["User-Agent"].startswith("vehiclesdb-python/"))
        # The documented 200 body comes back verbatim.
        self.assertEqual(payload, IMAGE_200)
        self.assertEqual(payload["variants"]["lg"]["width"], 1280)
        self.assertEqual(payload["color"], payload["requested_color"])

    def test_three_arg_addressing_builds_the_same_url(self):
        stub = StubTransport(200, IMAGE_200)
        self.client(stub).images("car", "renault", "clio")
        self.assertEqual(stub.calls[0][0], "%s/v1/vehicles/car/renault/clio/images" % API_BASE_URL)

    def test_format_is_passed_through(self):
        stub = StubTransport(200, dict(IMAGE_200, format="png"))
        self.client(stub).images("car/renault/clio", color="red", format="png")
        self.assertEqual(
            stub.calls[0][0],
            "%s/v1/vehicles/car/renault/clio/images?color=red&format=png" % API_BASE_URL,
        )

    def test_reserved_and_misspelled_filters_fail_locally(self):
        # `year`/`trim` 422 upstream by design; refusing them here costs no
        # round trip and makes `colour=` a TypeError rather than a silent grey.
        stub = StubTransport(200, IMAGE_200)
        with self.assertRaises(TypeError):
            self.client(stub).images("car/renault/clio", year=2019)
        with self.assertRaises(TypeError):
            self.client(stub).images("car/renault/clio", colour="blue")
        self.assertEqual(stub.calls, [])

    def test_404_no_image_becomes_a_api_error(self):
        stub = StubTransport(404, {"error": "no_image", "id": "car/volkswagen/passat"})
        with self.assertRaises(VehiclesDBApiError) as caught:
            self.client(stub).images("car/volkswagen/passat")
        self.assertEqual(caught.exception.status, 404)
        self.assertEqual(caught.exception.body["error"], "no_image")
        self.assertEqual(caught.exception.body["id"], "car/volkswagen/passat")

    def test_401_unauthorized_becomes_an_api_error(self):
        stub = StubTransport(401, {"error": "unauthorized"})
        with self.assertRaises(VehiclesDBApiError) as caught:
            self.client(stub, api_key="wrong").images("car/renault/clio")
        self.assertEqual(caught.exception.status, 401)
        self.assertEqual(caught.exception.body["error"], "unauthorized")

    def test_422_unknown_color_becomes_an_api_error(self):
        stub = StubTransport(422, {"error": "unknown_color", "palette": ["white", "black"]})
        with self.assertRaises(VehiclesDBApiError) as caught:
            self.client(stub).images("car/renault/clio", color="chartreuse")
        self.assertEqual(caught.exception.status, 422)
        self.assertEqual(caught.exception.body["error"], "unknown_color")

    def test_images_never_touches_the_dataset(self):
        # No dataset fallback exists: the open dataset has no imagery, so a
        # local answer would be a fiction.
        stub = StubTransport(200, IMAGE_200)
        self.client(stub).images("car/renault/clio")
        self.assertEqual(len(stub.calls), 1)


# ---------------------------------------------------------------------------
# laziness / memoization
# ---------------------------------------------------------------------------

class LazinessTest(OfflineTestCase):
    def test_constructing_performs_zero_transport_calls(self):
        VehiclesDB(dataset_base_url=DATASET_BASE_URL, transport=self.transport)
        self.assertEqual(self.transport.calls, [])

    def test_two_makes_calls_perform_exactly_one_fetch(self):
        self.db.makes()
        self.db.makes()
        self.assertEqual(len(self.transport.calls), 1)
        self.assertEqual(self.transport.urls, ["%s/dist/vehicles.json" % DATASET_BASE_URL])

    def test_the_catalog_is_fetched_only_for_a_full_record_and_once_per_kind(self):
        self.db.makes()
        self.db.models("VW")
        self.db.resolve("VW Golf")
        self.db.search("golf")
        self.assertEqual(len(self.transport.calls), 1, "only dist/ so far")

        self.db.model("car/volkswagen/golf")
        self.db.model("car/volkswagen/polo")
        self.assertEqual(
            self.transport.urls,
            [
                "%s/dist/vehicles.json" % DATASET_BASE_URL,
                "%s/catalog/car/models.json" % DATASET_BASE_URL,
            ],
        )

        self.db.model("van/volkswagen/caddy")
        self.assertEqual(
            self.transport.urls[-1], "%s/catalog/van/models.json" % DATASET_BASE_URL
        )

    def test_dataset_version_is_read_from_the_release(self):
        self.assertEqual(self.db.dataset_version, DIST["version"])
        self.assertEqual(self.db.dataset_version, "2026.07.6")
        self.assertEqual(self.db.kinds, DIST["kinds"])

    def test_default_dataset_base_url_matches_the_ruby_gem(self):
        # vehicles/lib/vehicles/configuration.rb:72 — same host, same repo,
        # same @version pin, so all three SDKs read the same bytes.
        self.assertEqual(
            VehiclesDB().dataset_base_url,
            "https://cdn.jsdelivr.net/gh/vehiclesdb/vehiclesdb@latest",
        )
        self.assertEqual(
            VehiclesDB(version="2026.07.6").dataset_base_url,
            "https://cdn.jsdelivr.net/gh/vehiclesdb/vehiclesdb@2026.07.6",
        )


# ---------------------------------------------------------------------------
# the offline guard itself
# ---------------------------------------------------------------------------

class OfflineGuardTest(unittest.TestCase):
    def test_an_unfixtured_url_raises_loudly(self):
        # If this ever stops raising, every other test in this file could be
        # silently hitting the network.
        transport = FixtureTransport()
        db = VehiclesDB(dataset_base_url="https://cdn.jsdelivr.net/gh/x/y@latest", transport=transport)
        with self.assertRaises(FixtureNotFound):
            db.makes()

    def test_a_missing_fixture_file_raises_loudly(self):
        transport = FixtureTransport()
        db = VehiclesDB(dataset_base_url=DATASET_BASE_URL, transport=transport)
        db.makes()
        with self.assertRaises(FixtureNotFound):
            # No catalog slice was cut for this kind in the fixture tree.
            db._catalog("submarine")


# ---------------------------------------------------------------------------
# attribution
# ---------------------------------------------------------------------------

class AttributionTest(OfflineTestCase):
    def test_notice_names_vehiclesdb_and_the_cc_by_url(self):
        notice = self.db.attribution
        self.assertIn("VehiclesDB", notice)
        self.assertIn("https://vehiclesdb.com", notice)
        self.assertIn("https://creativecommons.org/licenses/by/4.0/", notice)
        self.assertEqual(notice, ATTRIBUTION_TEXT)

    def test_html_snippet_is_the_form_the_data_repo_requests(self):
        self.assertEqual(
            self.db.attribution_html,
            '<a href="https://vehiclesdb.com">Vehicle data by VehiclesDB</a>',
        )

    def test_attribution_needs_no_network(self):
        # An integrator must be able to render credit before the first lookup.
        self.assertTrue(self.db.attribution)
        self.assertTrue(self.db.attribution_html)
        self.assertEqual(self.transport.calls, [])


# ---------------------------------------------------------------------------
# httpx is optional
# ---------------------------------------------------------------------------

class HttpxOptionalTest(OfflineTestCase):
    def test_nothing_imports_httpx(self):
        # httpx is NOT installed in this environment, which is the default
        # path: `import vehiclesdb` and every dataset-mode call must work
        # without it. Asserting on sys.modules catches an eager
        # `import httpx` at module scope even on a machine that has it.
        self.db.makes()
        self.db.models("VW")
        self.db.model("car/volkswagen/golf")
        self.db.resolve("VW Golf")
        self.db.search("golf")
        self.assertNotIn("httpx", sys.modules)

    def test_httpx_transport_is_exported_and_lazy(self):
        # Building the transport must not import httpx either — only calling
        # it without a client does.
        transport = httpx_transport()
        self.assertTrue(callable(transport))
        self.assertNotIn("httpx", sys.modules)

    def test_an_httpx_like_client_is_accepted_as_transport(self):
        class FakeResponse:
            status_code = 200

            def __init__(self, content):
                self.content = content

        class FakeClient:
            """Duck-typed httpx.Client — we never isinstance-check the real one."""

            def __init__(self):
                self.calls = []

            def get(self, url, headers=None):
                self.calls.append((url, headers))
                with open(
                    __import__("os").path.join(
                        __import__("helpers").FIXTURES_DIR, "dist", "vehicles.json"
                    ),
                    "rb",
                ) as handle:
                    return FakeResponse(handle.read())

        client = FakeClient()
        db = VehiclesDB(dataset_base_url=DATASET_BASE_URL, transport=client)
        self.assertEqual(len(db.makes()), 12)
        self.assertEqual(len(client.calls), 1)
        self.assertNotIn("httpx", sys.modules)

    def test_a_bad_transport_is_rejected_at_construction(self):
        with self.assertRaises(TypeError):
            VehiclesDB(transport=object())


if __name__ == "__main__":
    unittest.main()
