"""Exception types.

One base class so `except VehiclesDBError` catches everything this package
can raise, and specific subclasses so callers can branch without string
matching on messages.
"""

from typing import Any, Optional


class VehiclesDBError(Exception):
    """Base class for every error raised by this package."""


class MissingApiKeyError(VehiclesDBError):
    """Raised when an API-only method is called on a dataset-mode client.

    Carries the name of the constructor argument that was missing so callers
    (and error trackers) do not have to parse the message. Today only
    `images()` reaches this: it is the single `/v1` endpoint that exists, and
    it is authenticated — see https://vehiclesdb.com/api.
    """

    def __init__(self, method: str, argument: str = "api_key") -> None:
        self.method = method
        self.argument = argument
        super().__init__(
            "VehiclesDB.%s() needs an API key: construct the client with "
            "VehiclesDB(%s=\"...\"). Get one at https://vehiclesdb.com" % (method, argument)
        )


class VehiclesDBApiError(VehiclesDBError):
    """A non-2xx response from the hosted API at https://vehiclesdb.com.

    `status` is the HTTP status and `body` is the decoded JSON body when the
    response was JSON, else the raw text. The documented bodies are
    `{"error": "unauthorized"}` (401), `{"error": "no_image", "id": ...}` (404)
    and `{"error": "unknown_color", "palette": [...]}` /
    `{"error": "unsupported_filter", "filter": ...}` (422). We do not flatten
    them into separate exception classes: the endpoint's own YARD docs are the
    source of truth for that vocabulary and it will grow, so callers should
    read `err.body["error"]` rather than rely on a class hierarchy we would
    have to keep in lockstep.
    """

    def __init__(self, status: int, body: Any, url: Optional[str] = None) -> None:
        self.status = status
        self.body = body
        self.url = url
        code = body.get("error") if isinstance(body, dict) else None
        super().__init__(
            "VehiclesDB API returned %s%s%s"
            % (status, " (%s)" % code if code else "", " for %s" % url if url else "")
        )


class DatasetError(VehiclesDBError):
    """The published dataset could not be fetched or parsed.

    Raised for a non-200 on a CDN URL, for undecodable bytes, and for JSON that
    does not have the shape SCHEMA.md documents. It is deliberately loud: a
    silently-empty dataset would make every lookup return None/[] and look like
    a data problem rather than a network problem.
    """

    def __init__(self, message: str, url: Optional[str] = None, status: Optional[int] = None) -> None:
        self.url = url
        self.status = status
        super().__init__("%s%s" % (message, " (%s)" % url if url else ""))


class TransportError(VehiclesDBError):
    """The HTTP call never produced a response (DNS, TLS, timeout, refused).

    Distinct from DatasetError/VehiclesDBApiError, which both mean "a server
    answered, just not with what we wanted".
    """

    def __init__(self, url: str, cause: BaseException) -> None:
        self.url = url
        self.cause = cause
        super().__init__("could not reach %s: %s" % (url, cause))
