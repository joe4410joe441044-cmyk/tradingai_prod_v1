"""In-process mock MCP transport. It performs no network or file I/O."""
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence
from backend.execution.hyro_mcp_read_adapter import HyroMcpToolProfile

@dataclass
class MockHyroMcpServer:
    responses: dict[tuple[str, str | None], Mapping[str, Any]]
    advertised_tools: set[str]
    calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list)

    @classmethod
    def with_responses(cls, responses, *, include_write_tool=True):
        tools = set(HyroMcpToolProfile().by_operation().values())
        if include_write_tool: tools.add("mock.hyro.submit_order")
        return cls(dict(responses), tools)

    def list_tools(self) -> Sequence[str]: return tuple(sorted(self.advertised_tools))
    def call_tool(self, name: str, arguments: Mapping[str, Any]) -> Mapping[str, Any]:
        self.calls.append((name, dict(arguments)))
        key = (name, arguments.get("cursor"))
        if key not in self.responses: raise RuntimeError("mock response unavailable")
        return deepcopy(self.responses[key])

class DummyTokenMockTransport:
    def __init__(self, server: MockHyroMcpServer, token: str):
        if not token: raise ValueError("dummy token required")
        self._server, self._token = server, token
    def __repr__(self): return "DummyTokenMockTransport(token=<redacted>)"
    def list_tools(self): return self._server.list_tools()
    def call_tool(self, name, arguments):
        if self._token == "force-failure-dummy-token": raise RuntimeError("credential redacted")
        return self._server.call_tool(name, arguments)
