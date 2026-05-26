"""Shared fixtures for the AIR MCP server tests.

Strategy: we exercise the REAL MCP tool handlers and the REAL Python SDK,
mocking only the HTTP layer via httpx.MockTransport. That way:
  - The MCP @tool decorator paths get exercised
  - The SDK's request/response/error-mapping code gets exercised
  - The MCP-side error packing (_err) gets exercised
  - Only network I/O is faked

This catches any integration bug between MCP and SDK that pure unit-mocking
the SDK would hide.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest
from agent_identity_registry import AIRClient


@pytest.fixture
def mock_air(monkeypatch) -> Callable[..., AIRClient]:
    """Inject an AIRClient with a MockTransport into the MCP server's client cache.

    Usage:
        async def test_x(mock_air):
            mock_air({
                ("GET", "/api/v1/health"): (200, {"status": "ok", ...}),
            })
            _, data = await mcp.call_tool("air_health", {})
            assert data["status"] == "ok"

    monkeypatch auto-reverts the injection after the test, so each test
    starts fresh (the next test triggers a real _get_client() unless it
    also calls mock_air).
    """
    import air_mcp.server as server_module

    def _setup(
        routes: dict[tuple[str, str], tuple[int, dict[str, Any]]],
    ) -> AIRClient:
        def handler(request: httpx.Request) -> httpx.Response:
            key = (request.method, request.url.path)
            if key not in routes:
                return httpx.Response(
                    404,
                    json={"error": f"No mock route for {key!r}"},
                )
            status, body = routes[key]
            return httpx.Response(
                status,
                content=json.dumps(body),
                headers={"Content-Type": "application/json"},
            )

        client = AIRClient(
            base_url="https://test.invalid",
            transport=httpx.MockTransport(handler),
        )
        monkeypatch.setattr(server_module, "_client", client)
        return client

    return _setup


@pytest.fixture
def mock_air_transport(monkeypatch) -> Callable[..., AIRClient]:
    """Variant of mock_air that takes a raw handler callable.

    Use when you need to inspect the request (headers, body, params) or
    simulate transport-layer failures (raise httpx.ConnectError, etc.).
    """
    import air_mcp.server as server_module

    def _setup(handler: Callable[[httpx.Request], httpx.Response]) -> AIRClient:
        client = AIRClient(
            base_url="https://test.invalid",
            transport=httpx.MockTransport(handler),
        )
        monkeypatch.setattr(server_module, "_client", client)
        return client

    return _setup


@pytest.fixture(autouse=True)
def _reset_client_cache(monkeypatch):
    """Ensure every test starts with a clean module-level client cache.

    Without this, a test that doesn't use mock_air would inherit whatever
    client (real or mock) the previous test left behind.
    """
    import air_mcp.server as server_module
    monkeypatch.setattr(server_module, "_client", None)
