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
_MAX_DIAGNOSTIC_TEXT_BYTES = 250_000
_DIAGNOSTIC_TOOL_NAME = "list_challenges"
_LIST_CHALLENGES_PAYLOAD_FIELDS = frozenset(
    {"data", "page", "pageSize", "total", "totalPages"}
)
_FIXED_RESULT_FIELDS = frozenset({"structuredContent", "content", "isError"})
_FIXED_CONTENT_BLOCK_FIELDS = frozenset({"type", "text"})
_FIXED_PAYLOAD_FIELDS = frozenset(
    {
        "challenges", "items", "rows", "results", "data", "pagination",
        "page", "pageSize", "total", "totalCount", "totalItems",
        "totalPages", "hasNext", "hasNextPage", "nextPage", "nextCursor",
    }
)


class _DuplicateJsonKey(ValueError):
    pass


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


@dataclass(frozen=True)
class HyroMcpToolResultDiagnostics:
    """Value-free metadata for a single MCP tool result envelope."""

    classification: str
    result_field_types: tuple[tuple[str, str], ...]
    unknown_result_field_count: int
    content_block_count: int | None
    content_block_types: tuple[str, ...]
    unknown_content_block_field_count: int
    payload_object_available: bool
    text_json_parsed: bool
    payload_field_types: tuple[tuple[str, str], ...]
    unknown_payload_field_count: int


@dataclass(frozen=True, repr=False)
class HyroListChallengesResult:
    """Parsed envelope with still-unconfirmed list semantics.

    Challenge values are intentionally omitted from ``repr``. The observed
    envelope establishes only field names and types; it does not establish
    item meaning, account identity, or the terminal-page contract.
    """

    data: tuple[Any, ...] = field(repr=False)
    page: int = field(repr=False)
    page_size: int = field(repr=False)
    total: int = field(repr=False)
    total_pages: int = field(repr=False)
    result_format: str
    list_completeness: str = "UNKNOWN"
    account_match: str = "UNKNOWN"

    def __repr__(self) -> str:
        return (
            "HyroListChallengesResult(<values-redacted>, "
            f"result_format={self.result_format!r}, "
            f"list_completeness={self.list_completeness!r}, "
            f"account_match={self.account_match!r})"
        )


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
        result = self._call_allowed_tool(tool_name, arguments)
        structured = result.get("structuredContent")
        if not isinstance(structured, Mapping):
            raise HyroMcpHttpError("HYRO_MCP_TOOL_SCHEMA_UNCONFIRMED")
        return dict(structured)

    def call_tool_diagnostic(
        self,
        tool_name: str,
        arguments: Mapping[str, Any],
    ) -> HyroMcpToolResultDiagnostics:
        """Inspect one allowed result without exposing keys or payload values."""

        if tool_name != _DIAGNOSTIC_TOOL_NAME:
            raise PermissionError("MCP_DIAGNOSTIC_TOOL_NOT_ALLOWED")
        return self._diagnose_tool_result(self._call_allowed_tool(tool_name, arguments))

    def call_list_challenges(
        self,
        arguments: Mapping[str, Any],
    ) -> HyroListChallengesResult:
        """Call only ``list_challenges`` and validate its observed envelope."""

        result = self._call_allowed_tool(_DIAGNOSTIC_TOOL_NAME, arguments)
        payload, result_format = self._list_challenges_payload_object(result)
        return self._validate_list_challenges_payload(payload, result_format)

    def _call_allowed_tool(
        self,
        tool_name: str,
        arguments: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        if tool_name not in self._allowed_tool_names:
            raise PermissionError("MCP_TOOL_NOT_IN_READ_ALLOWLIST")
        inventory = frozenset(self.list_tools())
        if tool_name not in inventory:
            raise HyroMcpHttpError("HYRO_MCP_ALLOWED_TOOL_NOT_ADVERTISED")
        result = self._post("tools/call", {"name": tool_name, "arguments": dict(arguments)})
        if not isinstance(result, Mapping):
            raise HyroMcpHttpError("HYRO_MCP_TOOL_RESULT_INVALID")
        return result

    @classmethod
    def _diagnose_tool_result(
        cls,
        result: Mapping[str, Any],
    ) -> HyroMcpToolResultDiagnostics:
        result_types = cls._fixed_field_types(result, _FIXED_RESULT_FIELDS)
        unknown_result_count = cls._unknown_field_count(result, _FIXED_RESULT_FIELDS)
        base = {
            "result_field_types": result_types,
            "unknown_result_field_count": unknown_result_count,
            "content_block_count": None,
            "content_block_types": (),
            "unknown_content_block_field_count": 0,
            "payload_object_available": False,
            "text_json_parsed": False,
            "payload_field_types": (),
            "unknown_payload_field_count": 0,
        }
        is_error = result.get("isError", False)
        if not isinstance(is_error, bool):
            return HyroMcpToolResultDiagnostics(
                classification="IS_ERROR_TYPE_INVALID", **base
            )
        if is_error:
            return HyroMcpToolResultDiagnostics(
                classification="TOOL_REPORTED_ERROR", **base
            )

        if "structuredContent" in result:
            structured = result.get("structuredContent")
            if not isinstance(structured, Mapping):
                return HyroMcpToolResultDiagnostics(
                    classification="STRUCTURED_CONTENT_TYPE_INVALID", **base
                )
            return HyroMcpToolResultDiagnostics(
                classification="STRUCTURED_CONTENT_OBJECT",
                **{
                    **base,
                    "payload_object_available": True,
                    "payload_field_types": cls._fixed_field_types(
                        structured, _FIXED_PAYLOAD_FIELDS
                    ),
                    "unknown_payload_field_count": cls._unknown_field_count(
                        structured, _FIXED_PAYLOAD_FIELDS
                    ),
                },
            )

        content = result.get("content")
        if not isinstance(content, list):
            return HyroMcpToolResultDiagnostics(
                classification="CONTENT_TYPE_INVALID", **base
            )
        block_types = tuple(cls._content_block_type(block) for block in content)
        block_unknown_count = sum(
            cls._unknown_field_count(block, _FIXED_CONTENT_BLOCK_FIELDS)
            if isinstance(block, Mapping)
            else 0
            for block in content
        )
        content_base = {
            **base,
            "content_block_count": len(content),
            "content_block_types": block_types,
            "unknown_content_block_field_count": block_unknown_count,
        }
        if len(content) != 1:
            return HyroMcpToolResultDiagnostics(
                classification="CONTENT_BLOCK_COUNT_INVALID", **content_base
            )
        block = content[0]
        if not isinstance(block, Mapping) or block.get("type") != "text":
            return HyroMcpToolResultDiagnostics(
                classification="CONTENT_BLOCK_TYPE_UNSUPPORTED", **content_base
            )
        text = block.get("text")
        if not isinstance(text, str):
            return HyroMcpToolResultDiagnostics(
                classification="CONTENT_TEXT_TYPE_INVALID", **content_base
            )
        parse_classification, parsed = cls._strict_text_json_object(text)
        if parsed is None:
            return HyroMcpToolResultDiagnostics(
                classification=parse_classification, **content_base
            )
        return HyroMcpToolResultDiagnostics(
            classification="CONTENT_TEXT_JSON_OBJECT",
            **{
                **content_base,
                "payload_object_available": True,
                "text_json_parsed": True,
                "payload_field_types": cls._fixed_field_types(
                    parsed, _FIXED_PAYLOAD_FIELDS
                ),
                "unknown_payload_field_count": cls._unknown_field_count(
                    parsed, _FIXED_PAYLOAD_FIELDS
                ),
            },
        )

    @classmethod
    def _list_challenges_payload_object(
        cls,
        result: Mapping[str, Any],
    ) -> tuple[Mapping[str, Any], str]:
        if cls._unknown_field_count(result, _FIXED_RESULT_FIELDS):
            raise HyroMcpHttpError("HYRO_MCP_TOOL_RESULT_FIELDS_UNCONFIRMED")
        is_error = result.get("isError", False)
        if not isinstance(is_error, bool):
            raise HyroMcpHttpError("HYRO_MCP_TOOL_IS_ERROR_INVALID")
        if is_error:
            raise HyroMcpHttpError("HYRO_MCP_TOOL_REPORTED_ERROR")

        has_structured = "structuredContent" in result
        has_content = "content" in result
        structured = result.get("structuredContent")
        if has_structured and not isinstance(structured, Mapping):
            raise HyroMcpHttpError("HYRO_MCP_TOOL_STRUCTURED_CONTENT_INVALID")

        content_payload: Mapping[str, Any] | None = None
        if has_content:
            content = result.get("content")
            if not isinstance(content, list) or len(content) != 1:
                raise HyroMcpHttpError("HYRO_MCP_TOOL_CONTENT_BLOCKS_INVALID")
            block = content[0]
            if (
                not isinstance(block, Mapping)
                or cls._unknown_field_count(block, _FIXED_CONTENT_BLOCK_FIELDS)
                or block.get("type") != "text"
                or not isinstance(block.get("text"), str)
            ):
                raise HyroMcpHttpError("HYRO_MCP_TOOL_CONTENT_BLOCK_INVALID")
            classification, content_payload = cls._strict_text_json_object(block["text"])
            if content_payload is None:
                raise HyroMcpHttpError(f"HYRO_MCP_TOOL_{classification}")

        if has_structured and has_content:
            if dict(structured) != dict(content_payload or {}):
                raise HyroMcpHttpError("HYRO_MCP_TOOL_RESULT_FORMAT_CONFLICT")
            return structured, "STRUCTURED_AND_TEXT_EQUIVALENT"
        if has_structured:
            return structured, "STRUCTURED_CONTENT"
        if content_payload is not None:
            return content_payload, "CONTENT_TEXT_JSON_OBJECT"
        raise HyroMcpHttpError("HYRO_MCP_TOOL_SCHEMA_UNCONFIRMED")

    @classmethod
    def _validate_list_challenges_payload(
        cls,
        payload: Mapping[str, Any],
        result_format: str,
    ) -> HyroListChallengesResult:
        if frozenset(payload) != _LIST_CHALLENGES_PAYLOAD_FIELDS:
            raise HyroMcpHttpError("HYRO_MCP_LIST_CHALLENGES_FIELDS_UNCONFIRMED")
        if not isinstance(payload.get("data"), list):
            raise HyroMcpHttpError("HYRO_MCP_LIST_CHALLENGES_TYPES_INVALID")
        for name in ("page", "pageSize", "total", "totalPages"):
            if type(payload.get(name)) is not int:
                raise HyroMcpHttpError("HYRO_MCP_LIST_CHALLENGES_TYPES_INVALID")
        return HyroListChallengesResult(
            data=tuple(payload["data"]),
            page=payload["page"],
            page_size=payload["pageSize"],
            total=payload["total"],
            total_pages=payload["totalPages"],
            result_format=result_format,
        )

    @classmethod
    def _strict_text_json_object(
        cls,
        text: str,
    ) -> tuple[str, Mapping[str, Any] | None]:
        try:
            encoded = text.encode("utf-8")
        except UnicodeEncodeError:
            return "CONTENT_TEXT_ENCODING_INVALID", None
        if len(encoded) > _MAX_DIAGNOSTIC_TEXT_BYTES:
            return "CONTENT_TEXT_SIZE_EXCEEDED", None
        try:
            parsed = json.loads(
                text,
                object_pairs_hook=cls._strict_json_object,
                parse_constant=cls._reject_json_constant,
            )
        except (UnicodeError, ValueError, json.JSONDecodeError):
            return "CONTENT_TEXT_JSON_INVALID", None
        if not isinstance(parsed, Mapping):
            return "CONTENT_TEXT_JSON_NOT_OBJECT", None
        return "CONTENT_TEXT_JSON_OBJECT", parsed

    @staticmethod
    def _strict_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise _DuplicateJsonKey
            result[key] = value
        return result

    @staticmethod
    def _reject_json_constant(value: str) -> None:
        raise ValueError("non-standard JSON constant")

    @staticmethod
    def _value_type(value: object) -> str:
        if value is None:
            return "null"
        if isinstance(value, bool):
            return "boolean"
        if isinstance(value, int):
            return "integer"
        if isinstance(value, float):
            return "number"
        if isinstance(value, str):
            return "string"
        if isinstance(value, Mapping):
            return "object"
        if isinstance(value, list):
            return "array"
        return "unknown"

    @classmethod
    def _fixed_field_types(
        cls,
        value: Mapping[str, Any],
        allowed: frozenset[str],
    ) -> tuple[tuple[str, str], ...]:
        return tuple(
            (name, cls._value_type(value[name]))
            for name in sorted(allowed)
            if name in value
        )

    @staticmethod
    def _unknown_field_count(
        value: Mapping[str, Any],
        allowed: frozenset[str],
    ) -> int:
        return sum(1 for key in value if key not in allowed)

    @staticmethod
    def _content_block_type(block: object) -> str:
        if not isinstance(block, Mapping):
            return "invalid"
        block_type = block.get("type")
        if block_type in {"text", "image", "audio", "resource"}:
            return str(block_type)
        return "unknown"


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
