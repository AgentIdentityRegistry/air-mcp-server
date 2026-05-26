"""Tests for the 6 read-only AIR MCP tools.

Exercises real MCP + real SDK + mocked HTTP. Asserts both happy-path data
shapes AND the structured error contract that LLMs depend on.
"""

from __future__ import annotations

import httpx
import pytest

from air_mcp.server import _get_client, _err, mcp
from agent_identity_registry import AgentNotFoundError, RateLimitedError


# ----- Reusable response fixtures (mirror real API shapes) ---------------


HEALTH_BODY = {"status": "ok", "version": "0.1.0", "registry": "AIR"}

AGENT_LIST_BODY = {
    "agents": [
        {
            "air_id": "AIR-AAAA-BBBB-CCCC",
            "name": "TestBot",
            "description": "Test agent",
            "verified": True,
            "verification_level": "kyc-verified",
            "is_demo": False,
            "trust_score": 850,
            "trust_grade": "AA",
            "created": "2026-05-01T00:00:00.000Z",
        }
    ],
    "total": 1,
    "limit": 20,
    "offset": 0,
}

AGENT_FULL_BODY = {
    "@context": "https://agentidentityregistry.org/v1",
    "type": "AgentIdentity",
    "air_id": "AIR-AAAA-BBBB-CCCC",
    "name": "TestBot",
    "description": "Test agent",
    "creator": {
        "did": "did:web:example.com",
        "name": "Example",
        "type": "organization",
        "public_key": "A" * 43,
    },
    "capabilities": ["test"],
    "security": {"certifications": []},
    "transparency": {
        "open_source": True,
        "code_repository": "https://github.com/example/test",
        "documentation_url": "https://example.com/docs",
    },
    "verified": True,
    "verification_level": "kyc-verified",
    "is_demo": False,
    "status": "active",
    "created": "2026-05-01T00:00:00.000Z",
    "updated": "2026-05-01T00:00:00.000Z",
    "trust_score": 850,
    "trust_grade": "AA",
    "components": {
        "provenance": 800,
        "behavioral": 900,
        "transparency": 850,
        "security": 800,
        "peer_attestations": 900,
    },
}

TRUST_BODY = {
    "air_id": "AIR-AAAA-BBBB-CCCC",
    "total_score": 850,
    "grade": "AA",
    "components": {
        "provenance": 800,
        "behavioral": 900,
        "transparency": 850,
        "security": 800,
        "peer_attestations": 900,
    },
    "calculated_at": "2026-05-01T00:00:00.000Z",
}

DID_DOC_BODY = {
    "@context": [
        "https://www.w3.org/ns/did/v1",
        "https://w3id.org/security/suites/ed25519-2020/v1",
    ],
    "id": "did:wba:agentidentityregistry.org:agents:AIR-AAAA-BBBB-CCCC",
    "verificationMethod": [
        {
            "id": "did:wba:...#key-1",
            "type": "Ed25519VerificationKey2020",
            "controller": "did:wba:...",
            "publicKeyMultibase": "z6Mk1234567890",
        }
    ],
    "authentication": ["did:wba:...#key-1"],
    "assertionMethod": ["did:wba:...#key-1"],
    "service": [],
}

NAME_CHECK_BODY = {
    "name": "TestBot",
    "exists": False,
    "count": 0,
    "existing_agents": [],
}


# ============================================================
# TOOL REGISTRATION — confirms our 6-read-only-tools contract
# ============================================================


class TestRegistration:
    async def test_exactly_six_tools_registered(self):
        tools = await mcp.list_tools()
        assert len(tools) == 6

    async def test_tool_names_match_decision_doc(self):
        """Per air/mcp-server-architecture-decision: only these 6 read-only tools at launch."""
        tools = await mcp.list_tools()
        names = {t.name for t in tools}
        assert names == {
            "air_health",
            "air_list_agents",
            "air_lookup_agent",
            "air_trust_score",
            "air_did_document",
            "air_check_name",
        }

    async def test_no_write_tools_leaked(self):
        """Defensive: if someone accidentally exposes register/update, fail loud."""
        tools = await mcp.list_tools()
        names = {t.name for t in tools}
        for forbidden in ("air_register_agent", "air_update_agent", "air_delete_agent"):
            assert forbidden not in names, f"v0.1 must be read-only; found {forbidden}"

    async def test_every_tool_has_a_description(self):
        """LLM tool-selection depends on quality descriptions."""
        tools = await mcp.list_tools()
        for t in tools:
            assert t.description, f"tool {t.name} missing description"
            assert len(t.description) > 30, f"tool {t.name} description too short"


# ============================================================
# HAPPY PATHS — one test per tool
# ============================================================


class TestHappyPaths:
    async def test_air_health(self, mock_air):
        mock_air({("GET", "/api/v1/health"): (200, HEALTH_BODY)})
        _, data = await mcp.call_tool("air_health", {})
        assert data == {"status": "ok", "version": "0.1.0", "registry": "AIR"}

    async def test_air_list_agents(self, mock_air):
        mock_air({("GET", "/api/v1/agents"): (200, AGENT_LIST_BODY)})
        _, data = await mcp.call_tool("air_list_agents", {"limit": 20, "offset": 0})
        assert data["total"] == 1
        assert data["agents"][0]["name"] == "TestBot"
        assert data["agents"][0]["trust_grade"] == "AA"

    async def test_air_lookup_agent(self, mock_air):
        mock_air({("GET", "/api/v1/agents/AIR-AAAA-BBBB-CCCC"): (200, AGENT_FULL_BODY)})
        _, data = await mcp.call_tool("air_lookup_agent", {"air_id": "AIR-AAAA-BBBB-CCCC"})
        assert data["name"] == "TestBot"
        assert data["creator"]["type"] == "organization"
        assert data["components"]["provenance"] == 800

    async def test_air_trust_score(self, mock_air):
        mock_air(
            {("GET", "/api/v1/agents/AIR-AAAA-BBBB-CCCC/trust-score"): (200, TRUST_BODY)}
        )
        _, data = await mcp.call_tool("air_trust_score", {"air_id": "AIR-AAAA-BBBB-CCCC"})
        assert data["total_score"] == 850
        assert data["grade"] == "AA"
        assert data["components"]["behavioral"] == 900

    async def test_air_did_document_preserves_camelcase_via_by_alias(self, mock_air):
        """The W3C DID spec requires camelCase wire keys. MCP must output them
        as-spec'd so any DID-consuming LLM client sees the canonical shape."""
        mock_air(
            {("GET", "/api/v1/agents/AIR-AAAA-BBBB-CCCC/did-document"): (200, DID_DOC_BODY)}
        )
        _, data = await mcp.call_tool(
            "air_did_document", {"air_id": "AIR-AAAA-BBBB-CCCC"}
        )
        # Spec keys, not Pythonic snake_case:
        assert "verificationMethod" in data
        assert "assertionMethod" in data
        assert "publicKeyMultibase" in data["verificationMethod"][0]
        assert data["verificationMethod"][0]["type"] == "Ed25519VerificationKey2020"

    async def test_air_check_name(self, mock_air):
        mock_air({("GET", "/api/v1/agents/check-name"): (200, NAME_CHECK_BODY)})
        _, data = await mcp.call_tool("air_check_name", {"name": "TestBot"})
        assert data["exists"] is False
        assert data["count"] == 0


# ============================================================
# ERROR PATHS — every tool must return structured dicts, not raise
# ============================================================


class TestStructuredErrors:
    """LLMs depend on getting {error, status_code, error_class, ...} back —
    raising raw exceptions would surface as opaque MCP -32603 internal errors."""

    async def test_lookup_404_returns_agent_not_found(self, mock_air):
        mock_air(
            {
                ("GET", "/api/v1/agents/AIR-NONE-NONE-NONE"): (
                    404,
                    {"error": "Agent not found", "air_id": "AIR-NONE-NONE-NONE"},
                )
            }
        )
        _, data = await mcp.call_tool("air_lookup_agent", {"air_id": "AIR-NONE-NONE-NONE"})
        assert data["error_class"] == "AgentNotFoundError"
        assert data["status_code"] == 404
        assert data["air_id"] == "AIR-NONE-NONE-NONE"
        assert "Agent not found" in data["error"]

    async def test_trust_score_404_returns_structured(self, mock_air):
        mock_air(
            {
                ("GET", "/api/v1/agents/AIR-MISS-MISS-MISS/trust-score"): (
                    404,
                    {"error": "Trust score not found"},
                )
            }
        )
        _, data = await mcp.call_tool("air_trust_score", {"air_id": "AIR-MISS-MISS-MISS"})
        assert data["error_class"] == "AgentNotFoundError"
        assert data["air_id"] == "AIR-MISS-MISS-MISS"

    async def test_did_document_404_when_no_public_key(self, mock_air):
        """API returns 404 with a hint when the agent has no public_key on file."""
        mock_air(
            {
                ("GET", "/api/v1/agents/AIR-KEYLESS-X/did-document"): (
                    404,
                    {
                        "error": "Agent has no public key on file; DID document not available.",
                        "hint": "Register with a public_key field to enable resolution.",
                    },
                )
            }
        )
        _, data = await mcp.call_tool("air_did_document", {"air_id": "AIR-KEYLESS-X"})
        assert data["error_class"] == "AgentNotFoundError"
        assert "no public key" in data["error"]

    async def test_rate_limit_exposes_retry_after_seconds(self, mock_air):
        """LLM needs to know HOW LONG to back off, not just THAT it was rate-limited."""
        mock_air(
            {
                ("GET", "/api/v1/agents/AIR-AAAA-BBBB-CCCC"): (
                    429,
                    {"error": "Rate limit exceeded", "retry_after_seconds": 1800},
                )
            }
        )
        _, data = await mcp.call_tool("air_lookup_agent", {"air_id": "AIR-AAAA-BBBB-CCCC"})
        assert data["error_class"] == "RateLimitedError"
        assert data["status_code"] == 429
        assert data["retry_after_seconds"] == 1800

    async def test_server_error_returns_structured(self, mock_air):
        mock_air({("GET", "/api/v1/health"): (502, {"error": "Bad gateway"})})
        _, data = await mcp.call_tool("air_health", {})
        assert data["error_class"] == "ServerError"
        assert data["status_code"] == 502

    async def test_network_error_returns_structured(self, mock_air_transport):
        """Transport-layer failures (DNS, TLS, connection refused) must also
        return a dict, not propagate as exceptions."""

        def handler(_: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("simulated DNS failure")

        mock_air_transport(handler)
        _, data = await mcp.call_tool("air_health", {})
        assert data["error_class"] == "NetworkError"
        assert data["status_code"] is None  # NetworkError has no HTTP status


# ============================================================
# CLIENT CACHING + ENV-VAR CONFIG
# ============================================================


class TestClientCache:
    def test_get_client_lazy_inits_on_first_call(self):
        from air_mcp import server as server_module
        # Autouse _reset_client_cache fixture set this to None already.
        assert server_module._client is None
        client = _get_client()
        assert client is not None
        # Second call returns the same instance (caching works).
        assert _get_client() is client

    def test_get_client_uses_default_base_url(self, monkeypatch):
        monkeypatch.delenv("AIR_BASE_URL", raising=False)
        client = _get_client()
        assert "agentidentityregistry.org" in client._base_url

    def test_get_client_respects_air_base_url_env(self, monkeypatch):
        monkeypatch.setenv("AIR_BASE_URL", "https://staging.example.com")
        client = _get_client()
        assert "staging.example.com" in client._base_url

    def test_get_client_respects_air_timeout_env(self, monkeypatch):
        monkeypatch.setenv("AIR_TIMEOUT", "5")
        client = _get_client()
        # httpx stores the timeout per-method on Timeout — read the connect timeout
        assert client._client.timeout.connect == 5.0


# ============================================================
# _err() ENVELOPE SHAPE — direct unit test
# ============================================================


class TestErrPacking:
    def test_basic_air_error_packed(self):
        e = AgentNotFoundError("nope", air_id="AIR-X", status_code=404)
        d = _err(e, air_id="AIR-X")
        assert d == {
            "error": "nope",
            "status_code": 404,
            "error_class": "AgentNotFoundError",
            "air_id": "AIR-X",
        }

    def test_rate_limited_includes_retry_after_automatically(self):
        e = RateLimitedError("slow down", retry_after_seconds=600)
        d = _err(e)
        assert d["error_class"] == "RateLimitedError"
        assert d["retry_after_seconds"] == 600

    def test_extra_kwargs_merge_into_payload(self):
        e = AgentNotFoundError("nope", status_code=404)
        d = _err(e, air_id="AIR-X", extra_context="from-test")
        assert d["air_id"] == "AIR-X"
        assert d["extra_context"] == "from-test"
