# -*- coding: utf-8 -*-
"""Upstream HTTP client for the Market Recorder proxy.

GET for read endpoints; POST for control endpoints (start/stop).  Timeout is
mandatory, retries are disabled, redirects are never followed, and no cookies,
credentials, or request bodies are ever sent.  Raw response bodies are never
logged.
"""

import uuid
from datetime import datetime, timezone

import httpx

from backend.services.http.recorder_url_builder import (
    RecorderProxyURLBuilderError,
    build_upstream_url,
)

MAX_RESPONSE_BYTES = 5 * 1024 * 1024  # 5 MiB hard cap


class RecorderUpstreamError(Exception):
    """Safe upstream error.  Only ``code`` and ``retryable`` are surfaced."""

    def __init__(self, code, retryable, status_code=None):
        super().__init__(code)
        self.code = code
        self.retryable = retryable
        self.status_code = status_code


def _control_metadata():
    """Generate one set of the Recorder's non-secret request metadata."""
    request_id = str(uuid.uuid4())
    request_nonce = uuid.uuid4().hex
    request_timestamp = datetime.now(timezone.utc).isoformat()
    return (
        {
            "Request-ID": request_id,
            "Request-Nonce": request_nonce,
            "Request-Timestamp": request_timestamp,
        },
        {
            "request_id": request_id,
            "request_nonce": request_nonce,
            "request_timestamp": request_timestamp,
        },
    )


class RecorderReadOnlyClient:
    """Async client for the fixed recorder proxy endpoints (GET + Control POST)."""

    def __init__(
        self,
        base_url,
        timeout_seconds=5.0,
        verify_tls=True,
        transport=None,
        max_response_bytes=MAX_RESPONSE_BYTES,
    ):
        self._base_url = base_url
        self._timeout_seconds = timeout_seconds
        self._verify_tls = verify_tls
        self._transport = transport
        self._max_response_bytes = max_response_bytes

    async def get_health(self):
        """Fetch the upstream recorder health payload (GET only)."""
        return await self.get("health")

    async def get_status(self):
        """Fetch the upstream recorder status payload (GET only)."""
        return await self.get("status")

    async def get_storage(self):
        """Fetch the upstream recorder storage payload (GET only)."""
        return await self.get("storage")

    async def get_archives(self, query_params=None):
        """Fetch the upstream recorder archives payload (GET only)."""
        return await self.get("archives", query_params=query_params)

    async def get(self, endpoint_key, query_params=None):
        """Perform one GET against a fixed endpoint and return the parsed
        JSON object.  ``query_params`` must already be validated/allowlisted
        by the service layer."""
        try:
            url = build_upstream_url(self._base_url, endpoint_key)
        except RecorderProxyURLBuilderError:
            raise RecorderUpstreamError(
                "market_recorder_proxy_configuration_error",
                retryable=False,
            ) from None

        timeout = httpx.Timeout(self._timeout_seconds)
        limits = httpx.Limits(max_connections=10)
        async with httpx.AsyncClient(
            timeout=timeout,
            verify=self._verify_tls,
            follow_redirects=False,
            limits=limits,
            transport=self._transport,
        ) as client:
            try:
                response = await client.get(
                    url,
                    params=query_params if query_params else None,
                    headers={"Accept": "application/json"},
                )
            except httpx.TimeoutException:
                raise RecorderUpstreamError(
                    "market_recorder_upstream_timeout",
                    retryable=True,
                ) from None
            except httpx.RequestError:
                raise RecorderUpstreamError(
                    "market_recorder_upstream_unavailable",
                    retryable=True,
                ) from None

        return self._validate_response(response)

    async def post(self, endpoint_key, body=None):
        """Perform one POST against a fixed control endpoint and return the
        parsed JSON object. Control metadata is automatically sent in the
        Recorder contract headers; only the caller-provided payload is sent
        in the JSON body.
        No automatic retries are applied."""
        try:
            url = build_upstream_url(self._base_url, endpoint_key)
        except RecorderProxyURLBuilderError:
            raise RecorderUpstreamError(
                "market_recorder_proxy_configuration_error",
                retryable=False,
            ) from None

        metadata_headers, metadata_body = _control_metadata()
        request_body = {**metadata_body, **(body or {})}
        headers = {"Accept": "application/json", **metadata_headers}

        timeout = httpx.Timeout(self._timeout_seconds)
        limits = httpx.Limits(max_connections=10)
        async with httpx.AsyncClient(
            timeout=timeout,
            verify=self._verify_tls,
            follow_redirects=False,
            limits=limits,
            transport=self._transport,
        ) as client:
            try:
                response = await client.post(
                    url,
                    json=request_body,
                    headers=headers,
                )
            except httpx.TimeoutException:
                raise RecorderUpstreamError(
                    "market_recorder_upstream_timeout",
                    retryable=True,
                ) from None
            except httpx.RequestError:
                raise RecorderUpstreamError(
                    "market_recorder_upstream_unavailable",
                    retryable=True,
                ) from None

        return self._validate_response(response)

    def _validate_response(self, response):
        if 300 <= response.status_code < 400:
            raise RecorderUpstreamError(
                "market_recorder_upstream_protocol_error",
                retryable=False,
                status_code=response.status_code,
            )
        if response.status_code < 200 or response.status_code >= 300:
            retryable = response.status_code >= 500
            code = (
                "market_recorder_upstream_unavailable"
                if retryable
                else "market_recorder_upstream_rejected"
            )
            raise RecorderUpstreamError(
                code,
                retryable=retryable,
                status_code=response.status_code,
            )

        content_length = response.headers.get("content-length")
        if content_length is not None:
            try:
                if int(content_length) > self._max_response_bytes:
                    raise RecorderUpstreamError(
                        "market_recorder_upstream_invalid_response",
                        retryable=False,
                    )
            except ValueError:
                raise RecorderUpstreamError(
                    "market_recorder_upstream_invalid_response",
                    retryable=False,
                ) from None

        content_type = response.headers.get("content-type", "")
        if "application/json" not in content_type.lower():
            raise RecorderUpstreamError(
                "market_recorder_upstream_invalid_response",
                retryable=False,
            )

        if len(response.content) > self._max_response_bytes:
            raise RecorderUpstreamError(
                "market_recorder_upstream_invalid_response",
                retryable=False,
            )

        try:
            payload = response.json()
        except ValueError:
            raise RecorderUpstreamError(
                "market_recorder_upstream_invalid_response",
                retryable=False,
            ) from None
        if not isinstance(payload, dict):
            raise RecorderUpstreamError(
                "market_recorder_upstream_invalid_response",
                retryable=False,
            )
        return payload
