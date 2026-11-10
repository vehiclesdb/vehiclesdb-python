"""0.2.0 dogfooding additions: the kind-collision rule (RESOLUTION.md §3a),
`kinds`, id helpers, typed API errors, the country catalog and the labels.
Mirrors the JS SDK's tests of the same names."""
import json
import socket
import unittest
import urllib.error

from helpers import API_BASE_URL, DATASET_BASE_URL, OfflineTestCase, StubTransport  # noqa: E402

from vehiclesdb import (  # noqa: E402
    VehiclesDB,
    VehiclesDBApiError,
    VehiclesDBAuthError,
    VehiclesDBNotFoundError,
    VehiclesDBPaymentRequiredError,
    VehiclesDBRateLimitError,
    VehiclesDBTimeoutError,
    urllib_transport,
)

COLLISIONS = {"version": "1", "kinds": ["bus", "car", "moped", "motorcycle", "truck", "van"], "makes": [
    {"name": "Iveco", "slug": "iveco", "kinds": ["bus", "truck", "van"], "models": [
        {"name": "Daily", "slug": "daily", "kind": "bus", "global_decile": 2, "mass_decile": 1, "forms": ["Turbo", "Turbodaily"]},
        {"name": "Daily", "slug": "daily", "kind": "truck", "global_decile": 1, "mass_decile": 1, "forms": ["Turbo", "Turbodaily"]},
        {"name": "Daily", "slug": "daily", "kind": "van", "global_decile": 3, "mass_decile": 1, "forms": ["Turbodaily"],
         "former_ids": ["van/iveco/35s"], "registration_years": {"first": 1978, "last": 2026}},
    ]},
    {"name": "Mercedes-Benz", "slug": "mercedes-benz", "kinds": ["car", "van"], "models": [
        {"name": "V-Class", "slug": "v-class", "kind": "car", "mass_decile": 1, "availability": ["es"]},
        {"name": "V-Class", "slug": "v-class", "kind": "van", "global_decile": 1, "mass_decile": 2},
    ]},
    {"name": "Renault", "slug": "renault", "kinds": ["truck"], "former_slugs": ["renault-trucks"], "models": [
        {"name": "Master", "slug": "master", "kind": "truck"},
    ]},
    {"name": "Toyota", "slug": "toyota", "kinds": ["car"], "models": [
        {"name": "Corolla", "slug": "corolla", "kind": "car", "availability": ["es"]},
        {"name": "Corona", "slug": "corona", "kind": "car"},
    ]},
]}


def client(data=COLLISIONS):
    body = json.dumps(data).encode("utf-8")
    return VehiclesDB(transport=lambda url, headers: (200, body))


class KindCollisionTest(unittest.TestCase):
    def test_unhinted_collision_uses_the_shared_tie_break(self):
        db = client()
        for r in (db.resolve("iveco daily"), db.model_match("Iveco", "Daily")):
            self.assertEqual(r.id, "van/iveco/daily")
            self.assertFalse(r.ambiguous)
            self.assertEqual(r.method, "fold")
            self.assertEqual(sorted(m.kind for m in r.alternates), ["bus", "truck"])
        self.assertEqual(db.model_match("Mercedes-Benz", "V-Class").id, "car/mercedes-benz/v-class")

    def test_only_records_the_rung_matched_compete(self):
        db = client()
        self.assertEqual(db.model_match("Iveco", "Turbodaily").id, "van/iveco/daily")
        self.assertEqual(db.model_match("Iveco", "Turbo").id, "bus/iveco/daily")

    def test_typo_ties_within_one_nameplate_are_not_ambiguous(self):
        db = client()
        r = db.model_match("Iveco", "Dialy")
        self.assertEqual((r.id, r.method, r.confident), ("van/iveco/daily", "fuzzy", False))
        self.assertTrue(db.model_match("Toyota", "Corola").ambiguous)

    def test_kind_scopes_and_kinds_constrains(self):
        db = client()
        self.assertEqual(db.resolve("iveco daily", kind="truck").id, "truck/iveco/daily")
        self.assertEqual(db.resolve("iveco daily", kinds=["truck", "bus"]).id, "bus/iveco/daily")
        self.assertIsNone(db.resolve("iveco daily", kinds=[]))
        self.assertIsNone(db.resolve("bus/iveco/daily", kinds=["car"]))
        self.assertEqual(db.resolve("bus/iveco/daily", kind="car").id, "bus/iveco/daily")
        self.assertTrue(db.resolve("iveco daily").confident)

    def test_make_former_slugs(self):
        r = client().model_match("Renault Trucks", "Master")
        self.assertEqual(r.id, "truck/renault/master")
        self.assertIn("former_make_slug:renault trucks→renault", r.via)


class IdHelpersTest(unittest.TestCase):
    def test_by_id_and_successor(self):
        db = client()
        self.assertEqual(db.by_id("van/iveco/35s").id, "van/iveco/daily")
        self.assertIsNone(db.by_id("van/iveco/35s", follow=False))
        self.assertIsNone(db.by_id("van/iveco/daily", kinds=["car"]))
        self.assertEqual(db.successor("VAN/iveco/35s"), "van/iveco/daily")
        self.assertEqual(db.successor("bus/iveco/daily"), "bus/iveco/daily")
        self.assertIsNone(db.successor("car/nope/nope"))

    def test_new_record_fields(self):
        db = client()
        van = db.by_id("van/iveco/daily")
        self.assertEqual(van.mass_decile, 1)
        self.assertEqual(van.registration_years, {"first": 1978, "last": 2026})
        self.assertIsNone(db.by_id("bus/iveco/daily").registration_years)
        self.assertEqual(db.by_id("bus/iveco/daily").aliases, [])


class CatalogAndLabelsTest(unittest.TestCase):
    def test_catalog_filters_by_kind_and_country(self):
        db = client()
        es = db.catalog(country="ES")
        self.assertEqual([(e["make"].slug, [m.id for m in e["models"]]) for e in es],
                         [("mercedes-benz", ["car/mercedes-benz/v-class"]), ("toyota", ["car/toyota/corolla"])])
        self.assertEqual([e["make"].slug for e in db.catalog(kind="van")], ["iveco", "mercedes-benz"])
        self.assertEqual(db.catalog(kinds=[]), [])

    def test_labels(self):
        db = client()
        self.assertEqual(db.kind_label("van", "es"), "Furgoneta")
        self.assertEqual(db.kind_label("van"), "Van")
        self.assertIsNone(db.kind_label("hovercraft"))
        self.assertEqual(db.body_type_label("wagon", "es-ES"), "Familiar")
        self.assertEqual(db.color_options("es")[0], ("Blanco", "white"))
        self.assertEqual(len(db.colors()), 14)
        for text, slug in [("Marrón", "brown"), ("marron", "brown"), ("gris", "grey"), ("GRAY", "grey"),
                           ("plateado", "silver"), ("red", "red")]:
            self.assertEqual(db.color(text)["slug"], slug, text)
        self.assertEqual(db.color("rojo", "es")["name"], "Rojo")
        self.assertIsNone(db.color("chartreuse"))


class TypedErrorsTest(unittest.TestCase):
    def images(self, status, body):
        db = VehiclesDB(dataset_base_url=DATASET_BASE_URL, api_base_url=API_BASE_URL, api_key="k",
                        transport=StubTransport(status, body))
        return db.images("car/renault/clio")

    def test_statuses_map_to_typed_errors_with_code(self):
        for status, body, cls in [
            (401, {"error": "invalid_token"}, VehiclesDBAuthError),
            (402, {"error": "insufficient_credits"}, VehiclesDBPaymentRequiredError),
            (404, {"error": "no_render"}, VehiclesDBNotFoundError),
            (429, {"error": "rate_limited", "retry_after": 60}, VehiclesDBRateLimitError),
            (422, {"error": "unknown_color"}, VehiclesDBApiError),
        ]:
            with self.assertRaises(cls) as caught:
                self.images(status, body)
            self.assertIsInstance(caught.exception, VehiclesDBApiError)
            self.assertEqual(caught.exception.status, status)
            self.assertEqual(caught.exception.code, body["error"])
            if status == 429:
                self.assertEqual(caught.exception.retry_after, 60)

    def test_urllib_timeout_is_typed(self):
        import urllib.request
        original = urllib.request.urlopen

        def slow(*args, **kwargs):
            raise urllib.error.URLError(socket.timeout("timed out"))
        urllib.request.urlopen = slow
        try:
            with self.assertRaises(VehiclesDBTimeoutError):
                urllib_transport(0.01)("https://example.invalid/x", {})
        finally:
            urllib.request.urlopen = original


class ImagesPathTest(OfflineTestCase):
    api_key = "k"

    def test_images_calls_the_api_v1_path(self):
        stub = StubTransport(200, {"id": "car/renault/clio"})
        db = VehiclesDB(dataset_base_url=DATASET_BASE_URL, api_base_url=API_BASE_URL, api_key="k", transport=stub)
        db.images("car/renault/clio")
        self.assertEqual(stub.calls[0][0], "%s/api/v1/vehicles/car/renault/clio/images" % API_BASE_URL)


if __name__ == "__main__":
    unittest.main()
