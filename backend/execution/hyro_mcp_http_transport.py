"""Pinned Hyro MCP HTTP transport with discovery separated from tool calls.

The official endpoint, HTTP transport and Bearer header are configuration facts
supplied by the authenticated Hyro setup guide. Tool names and account payload
schemas are deliberately not guessed here. Importing or constructing these
classes never resolves a credential or opens a socket.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import json
import re
from typing import Any, Callable, Mapping, Protocol, Sequence
from urllib.parse import urlsplit

import requests

from backend.execution.hyro_mcp_connection import HyroMcpConnectionConfig
from backend.execution.hyro_mcp_read_adapter import HyroMcpReadTransport

HYRO_OFFICIAL_MCP_ENDPOINT = "https://mcp-public.hyro.trade/mcp"
HYRO_OFFICIAL_MCP_TRANSPORT = "HTTP"
HYRO_OFFICIAL_MCP_AUTH_SCHEME = "BEARER"
MCP_HANDSHAKE_PROTOCOL_VERSION = "2025-11-25"

_SAFE_REFERENCE = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,127}$")
_SAFE_TOOL_NAME = re.compile(r"^[^\x00-\x20\x7f]{1,256}$")
_MAX_TOKEN_LENGTH = 16_384


class HyroMcpCredentialResolver(Protocol):
    def resolve(self, reference: str) -> str: ...


class HyroMcpHttpError(RuntimeError):
    """Safe error whose text never includes response bodies or credentials."""

    def __init__(self, safe_code: str) -> None:
        self.safe_code = safe_code
        super().__init__(safe_code)


@dataclass(frozen=True)
class HyroMcpHttpConfig:
    credential_reference: str | None = field(default=None, repr=False)
    endpoint: str = HYRO_OFFICIAL_MCP_ENDPOINT
    protocol_version: str = MCP_HANDSHAKE_PROTOCOL_VERSION
    allow_network: bool = False
    timeout_seconds: float = 10.0
    max_response_bytes: int = 1_000_000
    max_tool_pages: int = 20

    def validate(self) -> None:
        if self.endpoint != HYRO_OFFICIAL_MCP_ENDPOINT:
            raise HyroMcpHttpError("HYRO_MCP_ENDPOINT_NOT_PINNED")
        parsed = urlsplit(self.endpoint)
        if (
            parsed.scheme != "https"
            or parsed.hostname != "mcp-public.hyro.trade"
            or parsed.port is not None
            or parsed.path != "/mcp"
            or parsed.query
            or parsed.fragment
            or parsed.username is not None
            or parsed.password is not None
        ):
            raise HyroMcpHttpError("HYRO_MCP_ENDPOINT_INVALID")
        if not self.credential_reference or not _SAFE_REFERENCE.fullmatch(self.credential_reference):
            raise HyroMcpHttpError("HYRO_MCP_CREDENTIAL_REFERENCE_MISSING")
        if not re.fullmatch(r"20[0-9]{2}-[0-9]{2}-[0-9]{2}", self.protocol_version):
            raise HyroMcpHttpError("HYRO_MCP_PROTOCOL_VERSION_INVALID")
        if type(self.allow_network) is not bool:
            raise HyroMcpHttpError("HYRO_MCP_NETWORK_GATE_INVALID")
        if isinstance(self.timeout_seconds, bool) or not isinstance(self.timeout_seconds, (int, float)):
            raise HyroMcpHttpError("HYRO_MCP_TIMEOUT_INVALID")
        if not 0 < float(self.timeout_seconds) <= 30:
            raise HyroMcpHttpError("HYRO_MCP_TIMEOUT_INVALID")
        if isinstance(self.max_response_bytes, bool) or not isinstance(self.max_response_bytes, int):
            raise HyroMcpHttpError("HYRO_MCP_RESPONSE_LIMIT_INVALID")
        if not 1 <= self.max_response_bytes <= 10_000_000:
            raise HyroMcpHttpError("HYRO_MCP_RESPONSE_LIMIT_INVALID")
        if isinstance(self.max_tool_pages, bool) or not isinstance(self.max_tool_pages, int):
            raise HyroMcpHttpError("HYRO_MCP_PAGE_LIMIT_INVALID")
        if not 1 <= self.max_tool_pages <= 100:
            raise HyroMcpHttpError("HYRO_MCP_PAGE_LIMIT_INVALID")


@dataclass(frozen=True)
class HyroMcpToolDescriptor:
    name: str
    description: str | None
    input_schema: Mapping[str, Any] | None
    output_schema: Mapping[str, Any] | None


@dataclass(frozen=True)
class HyroMcpDiscoveryResult:
    negotiated_protocol_version: str
    server_name: str | None
    server_version: str | None
    tools: tuple[HyroMcpToolDescriptor, ...]


class HyroMcpHttpTransport(HyroMcpReadTransport):
    """Streamable-HTTP preparation with an explicit network gate.

    ``initialize_and_list_tools`` performs metadata discovery only and never
    calls a tool. ``call_tool`` is for a later separately approved read phase
    and rejects every name outside the explicit constructor allowlist.
    """

    def __init__(
        self,
        config: HyroMcpHttpConfig,
        credential_resolver: HyroMcpCredentialResolver,
        *,
        allowed_tool_names: Sequence[str] = (),
        session: object | None = None,
    ) -> None:
        config.validate()
        if not hasattr(credential_resolver, "resolve"):
            raise TypeError("credential_resolver must provide resolve")
        allowed = frozenset(allowed_tool_names)
        if any(not isinstance(name, str) or not _SAFE_TOOL_NAME.fullmatch(name) for name in allowed):
            raise HyroMcpHttpError("HYRO_MCP_READ_ALLOWLIST_INVALID")
        self._config = config
        self._credential_resolver = credential_resolver
        self._allowed_tool_names = allowed
        self._session = session if session is not None else requests.Session()
        self._configure_session(self._session)
        self._request_id = 0
        self._session_id: str | None = None
        self._negotiated_version: str | None = None
        self._discovery: HyroMcpDiscoveryResult | None = None

    def __repr__(self) -> str:
        return (
            "HyroMcpHttpTransport("
            f"endpoint={HYRO_OFFICIAL_MCP_ENDPOINT!r}, "
            f"network_enabled={self._config.allow_network!r}, "
            f"allowed_tool_count={len(self._allowed_tool_names)!r})"
        )

    @staticmethod
    def _configure_session(session: object) -> None:
        for attribute, value in (("trust_env", False), ("proxies", {}), ("auth", None)):
            try:
                setattr(session, attribute, value)
            except Exception:
                pass
        headers = getattr(session, "headers", None)
        if hasattr(headers, "pop"):
            for name in ("Authorization", "Cookie"):
                try:
                    headers.pop(name, None)
                except Exception:
                    pass
        cookies = getattr(session, "cookies", None)
        if hasattr(cookies, "clear"):
            try:
                cookies.clear()
            except Exception:
                pass

    def _credential(self) -> str:
        if not self._config.allow_network:
            raise HyroMcpHttpError("HYRO_MCP_NETWORK_DISABLED")
        reference = self._config.credential_reference
        if not isinstance(reference, str):
            raise HyroMcpHttpError("HYRO_MCP_CREDENTIAL_REFERENCE_MISSING")
        try:
            token = self._credential_resolver.resolve(reference)
        except Exception:
            raise HyroMcpHttpError("HYRO_MCP_CREDENTIAL_UNAVAILABLE") from None
        if (
            not isinstance(token, str)
            or not token
            or len(token) > _MAX_TOKEN_LENGTH
            or token != token.strip()
            or any(ord(char) < 33 or ord(char) == 127 for char in token)
        ):
            raise HyroMcpHttpError("HYRO_MCP_CREDENTIAL_INVALID")
        return token

    def _headers(self, method: str) -> dict[str, str]:
        token = self._credential()
        headers = {
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        }
        if method != "initialize" and self._negotiated_version:
            headers["MCP-Protocol-Version"] = self._negotiated_version
        if self._session_id:
            headers["MCP-Session-Id"] = self._session_id
        return headers

    @staticmethod
    def _header(headers: object, name: str) -> str | None:
        getter = getattr(headers, "get", None)
        if callable(getter):
            for candidate in (name, name.lower(), name.upper()):
                try:
                    value = getter(candidate)
                except Exception:
                    value = None
                if isinstance(value, str):
                    return value
        items = getattr(headers, "items", None)
        if callable(items):
            try:
                for key, value in items():
                    if isinstance(key, str) and key.lower() == name.lower() and isinstance(value, str):
                        return value
            except Exception:
                return None
        return None

    def _next_id(self) -> int:
        self._request_id += 1
        return self._request_id

    def _post(
        self,
        method: str,
        params: Mapping[str, Any] | None,
        *,
        notification: bool = False,
    ) -> Mapping[str, Any] | None:
        request_id = None if notification else self._next_id()
        payload: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if request_id is not None:
            payload["id"] = request_id
        if params is not None:
            payload["params"] = dict(params)
        try:
            response = self._session.post(
                HYRO_OFFICIAL_MCP_ENDPOINT,
                json=payload,
                headers=self._headers(method),
                timeout=float(self._config.timeout_seconds),
                allow_redirects=False,
            )
        except HyroMcpHttpError:
            raise
        except Exception:
            raise HyroMcpHttpError("HYRO_MCP_TRANSPORT_FAILURE") from None
        status = getattr(response, "status_code", None)
        if isinstance(status, int) and 300 <= status < 400:
            raise HyroMcpHttpError("HYRO_MCP_REDIRECT_REJECTED")
        if status in (401, 403):
            raise HyroMcpHttpError("HYRO_MCP_AUTH_REJECTED")
        if notification and status in (200, 202, 204):
            body = getattr(response, "content", b"")
            if body in (b"", None):
                return None
        if status != 200:
            raise HyroMcpHttpError("HYRO_MCP_HTTP_STATUS_REJECTED")
        if method == "initialize":
            session_id = self._header(getattr(response, "headers", None), "MCP-Session-Id")
            if session_id is not None:
                if not session_id or len(session_id) > 256 or any(ord(char) < 33 or ord(char) == 127 for char in session_id):
                    raise HyroMcpHttpError("HYRO_MCP_SESSION_ID_INVALID")
                self._session_id = session_id
        message = self._decode_response(response)
        if notification:
            return None
        if message.get("id") != request_id or message.get("jsonrpc") != "2.0":
            raise HyroMcpHttpError("HYRO_MCP_RESPONSE_BINDING_INVALID")
        if "error" in message:
            raise HyroMcpHttpError("HYRO_MCP_REMOTE_ERROR")
        result = message.get("result")
        if not isinstance(result, Mapping):
            raise HyroMcpHttpError("HYRO_MCP_RESPONSE_INVALID")
        return result

    def _decode_response(self, response: object) -> Mapping[str, Any]:
        body = getattr(response, "content", None)
        if not isinstance(body, bytes) or len(body) > self._config.max_response_bytes:
            raise HyroMcpHttpError("HYRO_MCP_RESPONSE_INVALID")
        content_type = (self._header(getattr(response, "headers", None), "Content-Type") or "").lower()
        try:
            if "text/event-stream" in content_type:
                data_lines = [
                    line[5:].strip()
                    for line in body.decode("utf-8").splitlines()
                    if line.startswith("data:")
                ]
                if len(data_lines) != 1:
                    raise ValueError
                value = json.loads(data_lines[0])
            elif "application/json" in content_type:
                value = json.loads(body.decode("utf-8"))
            else:
                raise ValueError
        except (UnicodeDecodeError, ValueError, json.JSONDecodeError):
            raise HyroMcpHttpError("HYRO_MCP_RESPONSE_INVALID") from None
        if not isinstance(value, Mapping):
            raise HyroMcpHttpError("HYRO_MCP_RESPONSE_INVALID")
        return value

    def initialize_and_list_tools(self) -> HyroMcpDiscoveryResult:
        if self._discovery is not None:
            return self._discovery
        initialized = self._post(
            "initialize",
            {
                "protocolVersion": self._config.protocol_version,
                "capabilities": {},
                "clientInfo": {"name": "tradingai-read-only-intake", "version": "1.0"},
            },
        )
        if not isinstance(initialized, Mapping):
            raise HyroMcpHttpError("HYRO_MCP_INITIALIZE_INVALID")
        negotiated = initialized.get("protocolVersion")
        if not isinstance(negotiated, str) or not re.fullmatch(r"20[0-9]{2}-[0-9]{2}-[0-9]{2}", negotiated):
            raise HyroMcpHttpError("HYRO_MCP_INITIALIZE_INVALID")
        self._negotiated_version = negotiated
        server_info = initialized.get("serverInfo")
        server_name = server_info.get("name") if isinstance(server_info, Mapping) else None
        server_version = server_info.get("version") if isinstance(server_info, Mapping) else None
        server_name = server_name if isinstance(server_name, str) else None
        server_version = server_version if isinstance(server_version, str) else None
        self._post("notifications/initialized", None, notification=True)

        tools: list[HyroMcpToolDescriptor] = []
        cursor: str | None = None
        for _ in range(self._config.max_tool_pages):
            params = None if cursor is None else {"cursor": cursor}
            result = self._post("tools/list", params)
            if not isinstance(result, Mapping) or not isinstance(result.get("tools"), list):
                raise HyroMcpHttpError("HYRO_MCP_TOOL_LIST_INVALID")
            for raw in result["tools"]:
                tools.append(self._tool_descriptor(raw))
            next_cursor = result.get("nextCursor")
            if next_cursor in (None, ""):
                break
            if not isinstance(next_cursor, str) or next_cursor == cursor:
                raise HyroMcpHttpError("HYRO_MCP_TOOL_LIST_INVALID")
            cursor = next_cursor
        else:
            raise HyroMcpHttpError("HYRO_MCP_TOOL_LIST_INCOMPLETE")
        names = [tool.name for tool in tools]
        if len(names) != len(set(names)):
            raise HyroMcpHttpError("HYRO_MCP_TOOL_LIST_INVALID")
        self._discovery = HyroMcpDiscoveryResult(
            negotiated,
            server_name,
            server_version,
            tuple(tools),
        )
        return self._discovery

    @staticmethod
    def _tool_descriptor(raw: object) -> HyroMcpToolDescriptor:
        if not isinstance(raw, Mapping):
            raise HyroMcpHttpError("HYRO_MCP_TOOL_LIST_INVALID")
        name = raw.get("name")
        if not isinstance(name, str) or not _SAFE_TOOL_NAME.fullmatch(name):
            raise HyroMcpHttpError("HYRO_MCP_TOOL_LIST_INVALID")
        description = raw.get("description")
        description = description if isinstance(description, str) else None
        input_schema = raw.get("inputSchema")
        output_schema = raw.get("outputSchema")
        return HyroMcpToolDescriptor(
            name,
            description,
            dict(input_schema) if isinstance(input_schema, Mapping) else None,
            dict(output_schema) if isinstance(output_schema, Mapping) else None,
        )

    def list_tools(self) -> Sequence[str]:
        return tuple(tool.name for tool in self.initialize_and_list_tools().tools)

    def call_tool(self, tool_name: str, arguments: Mapping[str, Any]) -> Mapping[str, Any]:
        if tool_name not in self._allowed_tool_names:
            raise PermissionError("MCP_TOOL_NOT_IN_READ_ALLOWLIST")
        inventory = frozenset(self.list_tools())
        if tool_name not in inventory:
            raise HyroMcpHttpError("HYRO_MCP_ALLOWED_TOOL_NOT_ADVERTISED")
        result = self._post("tools/call", {"name": tool_name, "arguments": dict(arguments)})
        if not isinstance(result, Mapping):
            raise HyroMcpHttpError("HYRO_MCP_TOOL_RESULT_INVALID")
        structured = result.get("structuredContent")
        if not isinstance(structured, Mapping):
            raise HyroMcpHttpError("HYRO_MCP_TOOL_SCHEMA_UNCONFIRMED")
        return dict(structured)


class HyroOfficialMcpHttpTransportFactory:
    """Adapter factory for the existing fail-closed connection boundary."""

    def __init__(
        self,
        credential_resolver: HyroMcpCredentialResolver,
        *,
        allow_network: bool = False,
        session_factory: Callable[[], object] | None = None,
    ) -> None:
        self._credential_resolver = credential_resolver
        self._allow_network = allow_network
        self._session_factory = session_factory

    def __call__(self, config: HyroMcpConnectionConfig) -> HyroMcpHttpTransport:
        if (
            config.server_url != HYRO_OFFICIAL_MCP_ENDPOINT
            or config.transport != HYRO_OFFICIAL_MCP_TRANSPORT
            or config.auth_scheme != HYRO_OFFICIAL_MCP_AUTH_SCHEME
            or config.tools is None
        ):
            raise HyroMcpHttpError("HYRO_MCP_OFFICIAL_CONFIG_MISMATCH")
        allowed = tuple(config.tools.by_operation().values())
        session = self._session_factory() if self._session_factory is not None else None
        return HyroMcpHttpTransport(
            HyroMcpHttpConfig(
                credential_reference=config.credential_reference,
                endpoint=HYRO_OFFICIAL_MCP_ENDPOINT,
                allow_network=self._allow_network,
            ),
            self._credential_resolver,
            allowed_tool_names=allowed,
            session=session,
        )
