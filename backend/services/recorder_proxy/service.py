# -*- coding: utf-8 -*-
"""Service layer for the read-only Market Recorder proxy.

Route → Service → Client separation is preserved: routes never call the HTTP
client directly.  The service is responsible for configuration checks, enabled
state, query validation, upstream calls, envelope/DTO validation, and safe
error normalization.
"""

from datetime import datetime, timezone

from backend.config.recorder_proxy import (
    RecorderProxyConfig,
    RecorderProxyConfigError,
    load_recorder_proxy_config,
)
from backend.models.recorder_proxy import (
    RecorderProxyDTOError,
    VALIDATORS,
    validate_control_envelope,
    validate_envelope,
)
from backend.services.http.recorder_http_client import (
    RecorderReadOnlyClient,
    RecorderUpstreamError,
)
from backend.services.recorder_proxy.errors import map_control_status


class RecorderProxyDisabledError(Exception):
    """Proxy is not enabled (fail closed)."""


class RecorderProxyConfigurationError(Exception):
    """Proxy configuration is missing or invalid (fail closed)."""


class RecorderProxyQueryError(Exception):
    """One or more query parameters are invalid."""


ALLOWED_ARCHIVES_QUERY_KEYS = {
    "page",
    "page_size",
    "stream",
    "symbol",
    "from",
    "to",
    "verification_status",
    "downloadable",
    "sort",
    "order",
}

ALLOWED_SORT_FIELDS = {
    "start_time",
    "end_time",
    "record_count",
    "compressed_bytes",
    "verification_status",
}

ALLOWED_ORDER_VALUES = {"asc", "desc"}

ALLOWED_VERIFICATION_STATUS_VALUES = {"recording", "completed", "failed", "verified"}

ALLOWED_DOWNLOADABLE_VALUES = {"true", "false"}

NO_QUERY_ENDPOINTS = {"health", "status", "storage"}


def _as_mapping(query_params):
    if query_params is None:
        return {}
    if hasattr(query_params, "items"):
        return {key: value for key, value in query_params.items()}
    if isinstance(query_params, dict):
        return dict(query_params)
    return {}


def _strict_positive_int(value, name):
    if not value.isdigit():
        raise RecorderProxyQueryError()
    parsed = int(value)
    if parsed < 1:
        raise RecorderProxyQueryError()
    return parsed


def _parse_utc_iso(value, name):
    if not value.endswith("Z") and not value.endswith("+00:00"):
        raise RecorderProxyQueryError()
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        raise RecorderProxyQueryError() from None
    if parsed.tzinfo is None:
        raise RecorderProxyQueryError()
    return parsed.astimezone(timezone.utc)


def validate_archives_query(query_params):
    """Validate and filter archive query parameters.

    Unknown parameters are dropped (never forwarded upstream).  Known
    parameters are validated strictly and invalid values are rejected.
    """
    params = _as_mapping(query_params)
    result = {}

    for key, value in params.items():
        if key not in ALLOWED_ARCHIVES_QUERY_KEYS:
            continue

        if key == "page":
            result[key] = str(_strict_positive_int(value, key))
        elif key == "page_size":
            page_size = _strict_positive_int(value, key)
            if page_size > 200:
                raise RecorderProxyQueryError()
            result[key] = str(page_size)
        elif key == "sort":
            if value not in ALLOWED_SORT_FIELDS:
                raise RecorderProxyQueryError()
            result[key] = value
        elif key == "order":
            if value not in ALLOWED_ORDER_VALUES:
                raise RecorderProxyQueryError()
            result[key] = value
        elif key == "verification_status":
            if value not in ALLOWED_VERIFICATION_STATUS_VALUES:
                raise RecorderProxyQueryError()
            result[key] = value
        elif key == "downloadable":
            if value not in ALLOWED_DOWNLOADABLE_VALUES:
                raise RecorderProxyQueryError()
            result[key] = value
        elif key in ("stream", "symbol"):
            if not value:
                raise RecorderProxyQueryError()
            result[key] = value
        elif key in ("from", "to"):
            parsed = _parse_utc_iso(value, key)
            result[key] = value
            result[f"_{key}_parsed"] = parsed

    if "_from_parsed" in result and "_to_parsed" in result:
        if result["_from_parsed"] > result["_to_parsed"]:
            raise RecorderProxyQueryError()

    result.pop("_from_parsed", None)
    result.pop("_to_parsed", None)
    return result


def validate_no_query(query_params):
    """Health/status/storage endpoints forward no query parameters."""
    params = _as_mapping(query_params)
    if params:
        raise RecorderProxyQueryError()
    return {}



def _map_upstream_error(error):
    if error.code == "market_recorder_proxy_configuration_error":
        raise RecorderProxyConfigurationError() from error
    raise error


def _map_control_error(error):
    if error.code == "market_recorder_proxy_configuration_error":
        raise RecorderProxyConfigurationError() from error
    if error.status_code is not None:
        specific = map_control_status(error.status_code)
        if specific:
            raise RecorderUpstreamError(
                specific,
                retryable=error.retryable,
                status_code=error.status_code,
            ) from error
    raise error


class RecorderProxyService:
    """Coordinates configuration, query validation, upstream fetch, and DTO
    validation for the read-only recorder proxy."""

    def __init__(self, config=None, client=None):
        self.config = config
        self.configuration_error = False
        if self.config is None:
            try:
                self.config = load_recorder_proxy_config()
            except RecorderProxyConfigError:
                self.config = RecorderProxyConfig(
                    enabled=False,
                    base_url="",
                    timeout_seconds=5.0,
                    verify_tls=True,
                )
                self.configuration_error = True
        self._client = client

    def _ensure_ready(self):
        if self.configuration_error or not self.config.enabled:
            raise RecorderProxyDisabledError()
        if not self.config.base_url:
            raise RecorderProxyConfigurationError()

    def _make_client(self):
        if self._client is not None:
            return self._client
        return RecorderReadOnlyClient(
            base_url=self.config.base_url,
            timeout_seconds=self.config.timeout_seconds,
            verify_tls=self.config.verify_tls,
        )

    async def _fetch(self, endpoint_key, query_params):
        self._ensure_ready()
        client = self._make_client()
        try:
            payload = await client.get(endpoint_key, query_params=query_params)
        except RecorderProxyDTOError:
            raise
        except RecorderProxyQueryError:
            raise
        except RecorderUpstreamError as error:
            _map_upstream_error(error)
        except RecorderProxyConfigurationError:
            raise

        try:
            data = validate_envelope(payload)
            dto = VALIDATORS[endpoint_key](data)
        except RecorderProxyDTOError:
            raise
        return {"ok": True, "data": dto, "error": None}

    async def get_health(self, query_params=None):
        validate_no_query(query_params)
        return await self._fetch("health", {})

    async def get_status(self, query_params=None):
        validate_no_query(query_params)
        return await self._fetch("status", {})

    async def get_storage(self, query_params=None):
        validate_no_query(query_params)
        return await self._fetch("storage", {})

    async def get_archives(self, query_params=None):
        validated = validate_archives_query(query_params)
        return await self._fetch("archives", validated)

    async def _control_post(self, endpoint_key, body=None):
        self._ensure_ready()
        client = self._make_client()
        try:
            payload = await client.post(endpoint_key, body=body)
        except RecorderProxyDTOError:
            raise
        except RecorderUpstreamError as error:
            _map_control_error(error)

        try:
            data = validate_control_envelope(payload)
            dto = VALIDATORS[endpoint_key](data)
        except RecorderProxyDTOError:
            raise
        return {"ok": True, "data": dto, "error": None}

    async def start(self, dry_run=False):
        return await self._control_post("start", body={"dry_run": dry_run})

    async def stop(self, dry_run=False):
        return await self._control_post("stop", body={"dry_run": dry_run})
