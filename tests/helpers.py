"""Offline test rig: serve `fixtures/` through the transport seam.

The whole point of the injectable transport is that no test may touch the
network (CONTRACT.md, "Fixtures": *tests are offline by construction*). The
guard is `FixtureTransport`, which raises on any URL it has no file for — so a
test that reaches for an unfixtured URL fails loudly instead of quietly
succeeding against the real CDN on the maintainer's laptop and failing in CI.

It also counts calls, which is how the laziness assertions are written.
"""

import json
import os
import sys
import unittest
from typing import Dict, List, Optional, Tuple

# tests/ -> repo root -> fixtures/. The JS SDK (vehiclesdb/vehiclesdb-js)
# carries byte-identical fixtures; that sharing is what makes cross-language
# parity assertions meaningful, so never edit them by hand.
_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
PACKAGE_ROOT = os.path.dirname(_TESTS_DIR)
FIXTURES_DIR = os.path.join(PACKAGE_ROOT, "fixtures")

# Import the package from src/ without installing it. Keeps `python3 -m
# unittest discover -s tests` working in a bare checkout with no venv, which is
# how these tests are meant to be run.
sys.path.insert(0, os.path.join(PACKAGE_ROOT, "src"))

# An arbitrary but realistic base: the tests pass it as `dataset_base_url`, so
# they exercise the same URL construction the CDN default uses without ever
# building a jsdelivr URL that someone might accidentally let out.
DATASET_BASE_URL = "https://fixtures.test/vehiclesdb@2026.07.6"
API_BASE_URL = "https://api.test"


class FixtureNotFound(AssertionError):
    """Raised when a test asks for a URL the fixture tree cannot answer."""


class FixtureTransport:
    """`transport(url, headers) -> (status, bytes)` backed by fixtures/.

    Records every (url, headers) pair in `.calls` so tests can assert both how
    MANY requests were made (laziness/memoization) and what was on them
    (the Authorization header).
    """

    def __init__(self, base_url: str = DATASET_BASE_URL) -> None:
        self.base_url = base_url.rstrip("/")
        self.calls: List[Tuple[str, Dict[str, str]]] = []

    def __call__(self, url: str, headers: Dict[str, str]) -> Tuple[int, bytes]:
        self.calls.append((url, dict(headers)))
        if not url.startswith(self.base_url + "/"):
            raise FixtureNotFound(
                "test tried to fetch %r, which is not under the fixture base %r — "
                "this is the offline guard: no test may touch the network" % (url, self.base_url)
            )
        relative = url[len(self.base_url) + 1 :]
        path = os.path.join(FIXTURES_DIR, *relative.split("/"))
        if not os.path.isfile(path):
            raise FixtureNotFound(
                "no fixture file for %r (looked for %s). Regenerate with "
                "`python3 tools/make_fixtures.py --data-repo ../vehiclesdb`"
                % (url, path)
            )
        with open(path, "rb") as handle:
            return 200, handle.read()

    @property
    def urls(self) -> List[str]:
        return [url for url, _ in self.calls]


class StubTransport:
    """A canned (status, body) responder for the API-mode tests.

    `images()` talks to an endpoint that has no fixture on disk — it is a live
    service, not a published file — so its tests assert against the response
    shapes documented at https://vehiclesdb.com/api, transcribed here.
    """

    def __init__(self, status: int, payload) -> None:
        self.status = status
        self.payload = payload
        self.calls: List[Tuple[str, Dict[str, str]]] = []

    def __call__(self, url: str, headers: Dict[str, str]) -> Tuple[int, bytes]:
        self.calls.append((url, dict(headers)))
        return self.status, json.dumps(self.payload).encode("utf-8")


def load_fixture(*relative: str):
    """Read a fixture file directly, for tests that assert counts against reality."""
    with open(os.path.join(FIXTURES_DIR, *relative), encoding="utf-8") as handle:
        return json.load(handle)


class OfflineTestCase(unittest.TestCase):
    """Base case wiring a fresh client + fixture transport per test."""

    api_key: Optional[str] = None

    def setUp(self) -> None:
        from vehiclesdb import VehiclesDB

        self.transport = FixtureTransport()
        self.db = VehiclesDB(
            dataset_base_url=DATASET_BASE_URL,
            api_base_url=API_BASE_URL,
            api_key=self.api_key,
            transport=self.transport,
        )
