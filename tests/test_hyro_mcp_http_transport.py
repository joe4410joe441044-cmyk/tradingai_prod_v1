import json

import pytest

from backend.accounts.models import AccountId
from backend.execution.hyro_mcp_connection import HyroMcpConnectionConfig
from backend.execution.hyro_mcp_http_transport import (
    HYRO_OFFICIAL_MCP_AUTH_SCHEME,
    HYRO_OFFICIAL_MCP_ENDPOINT,
    HYRO_OFFICIAL_MCP_TRANSPORT,
    HyroMcpHttpConfig,
    HyroMcpHttpError,
    HyroMcpHttpTransport,
    HyroOfficialMcpHttpTransportFactory,
)
from backend.execution.hyro_mcp_read_adapter import HyroMcpAccountScope, HyroMcpToolProfile

DUMMY_TOKEN = "fixture-token-not-a-secret"
REFERENCE = "fixture-secure-store-reference"


class Resolver:
    def __init__(self, token=DUMMY_TOKEN):
        self.token = token
        self.calls = []

    def resolve(self, reference):
        self.calls.append(reference)
        return self.token


class Cookies:
    def __init__(self):
        self.cleared = False

    def clear(self):
        self.cleared = True


class Response:
    def __init__(self, status_code=200, payload=None, *, headers=None, body=None):
        self.status_code = status_code
        self.headers = {"Content-Type": "application/json", **(headers or {})}
        if body is not None:
            self.content = body
        elif payload is None:
            self.content = b""
        else:
            self.content = json.dumps(payload).encode()


class Session:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.headers = {"Authorization": "ambient", "Cookie": "ambient"}
        self.cookies = Cookies()
        self.trust_env = True
        self.proxies = {"https": "ambient"}
        self.auth = ("ambient", "ambient")

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if not self.responses:
            raise AssertionError("unexpected HTTP request")
        return self.responses.pop(0)


def rpc(request_id, result):
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def initialize_response(*, event_stream=False):
    payload = rpc(1, {
        "protocolVersion": "2025-11-25",
        "capabilities": {"tools": {"listChanged": False}},
        "serverInfo": {"name": "fixture-hyro", "version": "1"},
    })
    if event_stream:
        body = f"event: message\ndata: {json.dumps(payload)}\n\n".encode()
        return Response(headers={"Content-Type": "text/event-stream", "MCP-Session-Id": "fixture-session"}, body=body)
    return Response(payload=payload, headers={"MCP-Session-Id": "fixture-session"})


def tool_list_response(request_id=2):
    return Response(payload=rpc(request_id, {"tools": [
        {"name": "fixture.read_account", "description": "read", "inputSchema": {"type": "object"}},
        {"name": "fixture.place_order", "description": "write", "inputSchema": {"type": "object"}},
    ]}))


def transport(session, resolver=None, *, allowed=(), allow_network=True, reference=REFERENCE):
    return HyroMcpHttpTransport(
        HyroMcpHttpConfig(credential_reference=reference, allow_network=allow_network),
        resolver or Resolver(),
        allowed_tool_names=allowed,
        session=session,
    )


def test_initialize_and_list_tools_use_pinned_endpoint_bearer_and_execute_no_tool():
    resolver = Resolver()
    session = Session([initialize_response(), Response(status_code=202), tool_list_response()])
    subject = transport(session, resolver)

    discovery = subject.initialize_and_list_tools()

    assert [tool.name for tool in discovery.tools] == ["fixture.read_account", "fixture.place_order"]
    assert [call[1]["json"]["method"] for call in session.calls] == [
        "initialize", "notifications/initialized", "tools/list",
    ]
    assert all(url == HYRO_OFFICIAL_MCP_ENDPOINT for url, _ in session.calls)
    assert all(call[1]["headers"]["Authorization"] == f"Bearer {DUMMY_TOKEN}" for call in session.calls)
    assert all(call[1]["allow_redirects"] is False for call in session.calls)
    assert "MCP-Protocol-Version" not in session.calls[0][1]["headers"]
    assert session.calls[1][1]["headers"]["MCP-Protocol-Version"] == "2025-11-25"
    assert session.calls[1][1]["headers"]["MCP-Session-Id"] == "fixture-session"
    assert resolver.calls == [REFERENCE, REFERENCE, REFERENCE]
    assert session.trust_env is False and session.proxies == {} and session.auth is None
    assert session.cookies.cleared is True
    assert "Authorization" not in session.headers and "Cookie" not in session.headers


def test_sse_initialize_response_is_supported_without_tool_execution():
    session = Session([initialize_response(event_stream=True), Response(status_code=202), tool_list_response()])
    result = transport(session).initialize_and_list_tools()
    assert result.negotiated_protocol_version == "2025-11-25"
    assert all(call[1]["json"]["method"] != "tools/call" for call in session.calls)


def test_missing_reference_and_disabled_network_never_resolve_or_send():
    resolver = Resolver()
    session = Session([])
    with pytest.raises(HyroMcpHttpError, match="CREDENTIAL_REFERENCE_MISSING"):
        transport(session, resolver, reference=None)
    assert resolver.calls == [] and session.calls == []

    disabled = transport(session, resolver, allow_network=False)
    with pytest.raises(HyroMcpHttpError, match="NETWORK_DISABLED"):
        disabled.initialize_and_list_tools()
    assert resolver.calls == [] and session.calls == []


def test_redirect_is_not_followed_and_bearer_is_never_forwarded_to_other_host():
    resolver = Resolver()
    session = Session([Response(status_code=307, headers={"Location": "https://evil.invalid/mcp"})])
    with pytest.raises(HyroMcpHttpError, match="REDIRECT_REJECTED"):
        transport(session, resolver).initialize_and_list_tools()
    assert len(session.calls) == 1
    assert session.calls[0][0] == HYRO_OFFICIAL_MCP_ENDPOINT
    assert session.calls[0][1]["allow_redirects"] is False


def test_advertised_write_tool_is_not_authorized_and_read_allowlist_is_explicit():
    session = Session([initialize_response(), Response(status_code=202), tool_list_response(),
                       Response(payload=rpc(3, {"structuredContent": {"account_ref": "fixture"}}))])
    subject = transport(session, allowed=("fixture.read_account",))
    subject.initialize_and_list_tools()

    with pytest.raises(PermissionError, match="READ_ALLOWLIST"):
        subject.call_tool("fixture.place_order", {})
    assert [call[1]["json"]["method"] for call in session.calls].count("tools/call") == 0

    result = subject.call_tool("fixture.read_account", {})
    assert result == {"account_ref": "fixture"}
    assert session.calls[-1][1]["json"] == {
        "jsonrpc": "2.0", "id": 3, "method": "tools/call",
        "params": {"name": "fixture.read_account", "arguments": {}},
    }


def test_token_reference_and_token_are_masked_from_repr_and_errors():
    resolver = Resolver()
    session = Session([Response(status_code=401, body=b"secret server response")])
    subject = transport(session, resolver)
    with pytest.raises(HyroMcpHttpError) as captured:
        subject.initialize_and_list_tools()
    combined = repr(subject) + repr(subject._config) + str(captured.value)
    assert DUMMY_TOKEN not in combined
    assert REFERENCE not in combined
    assert "secret server response" not in combined


def test_factory_accepts_only_pinned_official_connection_settings():
    scope = HyroMcpAccountScope(
        AccountId("acc_20000000000040008000000000000002"),
        "fixture-account",
    )
    tools = HyroMcpToolProfile(
        account_identity="fixture.read_identity",
        account_summary="fixture.read_summary",
        positions="fixture.read_positions",
        open_orders="fixture.read_open_orders",
        conditional_orders="fixture.read_conditional_orders",
    )
    values = {
        "server_url": HYRO_OFFICIAL_MCP_ENDPOINT,
        "transport": HYRO_OFFICIAL_MCP_TRANSPORT,
        "auth_scheme": HYRO_OFFICIAL_MCP_AUTH_SCHEME,
        "credential_reference": REFERENCE,
        "response_schema_id": "fixture.pending-official-schema",
        "read_access_enabled": True,
        "trading_access_enabled": False,
    }
    config = HyroMcpConnectionConfig.from_mapping(values, account_scope=scope, tools=tools)
    factory = HyroOfficialMcpHttpTransportFactory(Resolver(), session_factory=lambda: Session([]))
    assert isinstance(factory(config), HyroMcpHttpTransport)

    wrong = HyroMcpConnectionConfig.from_mapping(
        {**values, "server_url": "https://other.invalid/mcp"}, account_scope=scope, tools=tools,
    )
    with pytest.raises(HyroMcpHttpError, match="OFFICIAL_CONFIG_MISMATCH"):
        factory(wrong)
