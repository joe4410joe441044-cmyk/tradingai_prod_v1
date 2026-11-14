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


def diagnostic_transport(result):
    session = Session([
        initialize_response(),
        Response(status_code=202),
        Response(payload=rpc(2, {"tools": [{"name": "list_challenges", "inputSchema": {"type": "object"}}]})),
        Response(payload=rpc(3, result)),
    ])
    return transport(session, allowed=("list_challenges",)), session


def test_cc6c_failure_reproduces_when_structured_content_is_missing():
    subject, session = diagnostic_transport({
        "content": [{"type": "text", "text": '{"challenges": []}'}],
        "isError": False,
    })

    with pytest.raises(HyroMcpHttpError, match="HYRO_MCP_TOOL_SCHEMA_UNCONFIRMED"):
        subject.call_tool("list_challenges", {})

    assert [call[1]["json"]["method"] for call in session.calls].count("tools/call") == 1


def test_diagnostic_preserves_structured_content_path_without_values():
    subject, _ = diagnostic_transport({
        "structuredContent": {
            "challenges": [{"publicId": "identifier-must-not-escape"}],
            "pagination": {"total": 1},
            "privateUnknownName": "secret-must-not-escape",
        },
        "isError": False,
    })

    result = subject.call_tool_diagnostic("list_challenges", {})

    assert result.classification == "STRUCTURED_CONTENT_OBJECT"
    assert result.payload_object_available is True
    assert result.text_json_parsed is False
    assert result.payload_field_types == (("challenges", "array"), ("pagination", "object"))
    assert result.unknown_payload_field_count == 1
    rendered = repr(result)
    assert "identifier-must-not-escape" not in rendered
    assert "secret-must-not-escape" not in rendered
    assert "privateUnknownName" not in rendered


def test_diagnostic_accepts_only_single_strict_text_json_object_without_values():
    subject, _ = diagnostic_transport({
        "content": [{
            "type": "text",
            "text": json.dumps({
                "challenges": [{"publicId": "identifier-must-not-escape"}],
                "pagination": {"page": 1, "total": 1},
                "privateUnknownName": "secret-must-not-escape",
            }),
            "privateBlockField": "secret-block-value",
        }],
        "isError": False,
        "privateResultField": "secret-result-value",
    })

    result = subject.call_tool_diagnostic("list_challenges", {})

    assert result.classification == "CONTENT_TEXT_JSON_OBJECT"
    assert result.result_field_types == (("content", "array"), ("isError", "boolean"))
    assert result.unknown_result_field_count == 1
    assert result.content_block_count == 1
    assert result.content_block_types == ("text",)
    assert result.unknown_content_block_field_count == 1
    assert result.payload_object_available is True
    assert result.text_json_parsed is True
    assert result.payload_field_types == (("challenges", "array"), ("pagination", "object"))
    assert result.unknown_payload_field_count == 1
    rendered = repr(result)
    for forbidden in (
        "identifier-must-not-escape",
        "secret-must-not-escape",
        "privateUnknownName",
        "privateBlockField",
        "secret-block-value",
        "privateResultField",
        "secret-result-value",
    ):
        assert forbidden not in rendered


@pytest.mark.parametrize(
    ("tool_result", "classification"),
    [
        ({"content": "not-a-list"}, "CONTENT_TYPE_INVALID"),
        ({"content": []}, "CONTENT_BLOCK_COUNT_INVALID"),
        ({"content": [{"type": "text", "text": "{}"}, {"type": "text", "text": "{}"}]}, "CONTENT_BLOCK_COUNT_INVALID"),
        ({"content": [{"type": "image", "data": "secret"}]}, "CONTENT_BLOCK_TYPE_UNSUPPORTED"),
        ({"content": [{"type": "text", "text": 7}]}, "CONTENT_TEXT_TYPE_INVALID"),
        ({"content": [{"type": "text", "text": "not-json"}]}, "CONTENT_TEXT_JSON_INVALID"),
        ({"content": [{"type": "text", "text": '{"page": 1, "page": 2}'}]}, "CONTENT_TEXT_JSON_INVALID"),
        ({"content": [{"type": "text", "text": "[]"}]}, "CONTENT_TEXT_JSON_NOT_OBJECT"),
        ({"structuredContent": [], "content": [{"type": "text", "text": "{}"}]}, "STRUCTURED_CONTENT_TYPE_INVALID"),
        ({"isError": "false", "content": [{"type": "text", "text": "{}"}]}, "IS_ERROR_TYPE_INVALID"),
    ],
)
def test_diagnostic_rejects_ambiguous_or_invalid_envelopes(tool_result, classification):
    subject, _ = diagnostic_transport(tool_result)
    result = subject.call_tool_diagnostic("list_challenges", {})
    assert result.classification == classification
    assert result.payload_object_available is False


def test_diagnostic_does_not_parse_tool_reported_error_content():
    subject, _ = diagnostic_transport({
        "isError": True,
        "content": [{"type": "text", "text": '{"secret": "must-not-escape"}'}],
    })

    result = subject.call_tool_diagnostic("list_challenges", {})

    assert result.classification == "TOOL_REPORTED_ERROR"
    assert result.content_block_count is None
    assert result.payload_object_available is False
    assert "must-not-escape" not in repr(result)


def test_diagnostic_keeps_json_rpc_remote_error_fail_closed_and_safe():
    session = Session([
        initialize_response(),
        Response(status_code=202),
        Response(payload=rpc(2, {"tools": [{"name": "list_challenges", "inputSchema": {"type": "object"}}]})),
        Response(payload={
            "jsonrpc": "2.0",
            "id": 3,
            "error": {"code": -32000, "message": "secret-remote-message"},
        }),
    ])
    subject = transport(session, allowed=("list_challenges",))

    with pytest.raises(HyroMcpHttpError, match="HYRO_MCP_REMOTE_ERROR") as captured:
        subject.call_tool_diagnostic("list_challenges", {})
    assert "secret-remote-message" not in str(captured.value)


def test_diagnostic_rejects_oversized_text_before_json_parsing():
    result = HyroMcpHttpTransport._diagnose_tool_result({
        "content": [{"type": "text", "text": "x" * 250_001}],
    })
    assert result.classification == "CONTENT_TEXT_SIZE_EXCEEDED"
    assert result.payload_object_available is False


def test_diagnostic_rejects_every_tool_except_list_challenges_before_network():
    subject, session = diagnostic_transport({"structuredContent": {}})
    with pytest.raises(PermissionError, match="MCP_DIAGNOSTIC_TOOL_NOT_ALLOWED"):
        subject.call_tool_diagnostic("fixture.place_order", {})
    assert session.calls == []
