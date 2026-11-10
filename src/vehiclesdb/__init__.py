"""vehiclesdb — vehicle makes, models and canonical ids, from the open dataset.

    from vehiclesdb import VehiclesDB

    db = VehiclesDB()
    db.resolve("VW Golf 1.9 TDI", kind="car").id      # "car/volkswagen/golf"

The product is the id: `kind/make_slug/model_slug`. Store that.

**Attribution is a licence condition.** The dataset is CC-BY 4.0 and §3(a)
requires visible credit — `db.attribution` returns the notice so you can render
it without copying prose.

Zero required dependencies: everything runs on `urllib.request` + `json`.
`httpx` is optional and is never imported unless you ask for it
(`vehiclesdb.httpx_transport`).
"""

from .client import (
    ATTRIBUTION_HTML,
    ATTRIBUTION_TEXT,
    DATASET_BASE_URL_TEMPLATE,
    DEFAULT_API_BASE_URL,
    KIND_PRECEDENCE,
    VehiclesDB,
    __version__,
    httpx_transport,
    urllib_transport,
)
from .errors import (
    DatasetError,
    MissingApiKeyError,
    TransportError,
    VehiclesDBApiError,
    VehiclesDBAuthError,
    VehiclesDBError,
    VehiclesDBNotFoundError,
    VehiclesDBPaymentRequiredError,
    VehiclesDBRateLimitError,
    VehiclesDBTimeoutError,
)
from .models import MATCH_CONFIDENCE, Make, Model, Resolution

__all__ = [
    "VehiclesDB",
    "Make",
    "Model",
    "Resolution",
    "MATCH_CONFIDENCE",
    "VehiclesDBError",
    "MissingApiKeyError",
    "VehiclesDBApiError",
    "VehiclesDBAuthError",
    "VehiclesDBPaymentRequiredError",
    "VehiclesDBNotFoundError",
    "VehiclesDBRateLimitError",
    "VehiclesDBTimeoutError",
    "KIND_PRECEDENCE",
    "DatasetError",
    "TransportError",
    "urllib_transport",
    "httpx_transport",
    "ATTRIBUTION_TEXT",
    "ATTRIBUTION_HTML",
    "DATASET_BASE_URL_TEMPLATE",
    "DEFAULT_API_BASE_URL",
    "__version__",
]
