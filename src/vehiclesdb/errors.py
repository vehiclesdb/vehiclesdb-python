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
    `images()` reaches this: it is the one API call this package makes, and
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

    `status` is the HTTP status, `body` the decoded JSON body when the response
    was JSON (else the raw text), and `code` the body's machine-readable
    `error` string (`invalid_token`, `insufficient_credits`, `rate_limited`,
    `unknown_model`, `no_render`, `unknown_color`, ...) or None. The statuses an integration
    handles differently raise the subclasses below; read `code` for the rest.
    """

    def __init__(self, status: int, body: Any, url: Optional[str] = None) -> None:
        self.status = status
        self.body = body
        self.url = url
        code = body.get("error") if isinstance(body, dict) else None
        self.code = code if isinstance(code, str) else None
        super().__init__(
            "VehiclesDB API returned %s%s%s"
            % (status, " (%s)" % self.code if self.code else "", " for %s" % url if url else "")
        )


class VehiclesDBAuthError(VehiclesDBApiError):
    """401/403: the key is missing, invalid or revoked, or not allowed here."""


class VehiclesDBPaymentRequiredError(VehiclesDBApiError):
    """402: the organization is out of API credits (`body["billing_url"]`)."""


class VehiclesDBNotFoundError(VehiclesDBApiError):
    """404: unknown resource or no image yet (`code` says which)."""


class VehiclesDBRateLimitError(VehiclesDBApiError):
    """429: an abuse ceiling. `retry_after` is in seconds (from the body), or None."""

    def __init__(self, status: int, body: Any, url: Optional[str] = None) -> None:
        super().__init__(status, body, url)
        value = body.get("retry_after") if isinstance(body, dict) else None
        self.retry_after = value if isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0 else None


_API_ERRORS = {401: VehiclesDBAuthError, 403: VehiclesDBAuthError, 402: VehiclesDBPaymentRequiredError,
               404: VehiclesDBNotFoundError, 429: VehiclesDBRateLimitError}


def api_error(status: int, body: Any, url: Optional[str] = None) -> VehiclesDBApiError:
    """The typed error for a non-2xx API response."""
    return _API_ERRORS.get(status, VehiclesDBApiError)(status, body, url)


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


class VehiclesDBTimeoutError(TransportError):
    """The request did not complete within the client's `timeout`."""
