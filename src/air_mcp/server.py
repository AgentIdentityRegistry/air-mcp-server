"""FastMCP server definition — six read-only AIR tools.

Tool prefix: `air_*` (per air/mcp-server-architecture-decision, to coexist
cleanly with BossClaw's future `bossclaw_*` MCP without collision).

Design notes:

* A single AIRClient is created lazily on first tool invocation and reused
  for the life of the server process. With stdio transport this lasts one
  Claude Code session; with streamable-HTTP it lasts as long as the process.
  Either way, httpx connection-pooling makes repeated tool calls fast.

* AirError subclasses are caught inside each tool and returned as structured
  dicts ({"error": ..., "status_code": ..., ...}) so the LLM can reason about
  the failure. Raising raw exceptions would surface as a generic MCP -32603
  internal error, which strips all useful context from the model.

* All tool returns are plain dicts (via Pydantic `.model_dump(mode="json")`).
  Datetimes are serialized as ISO strings; nested models flattened. The LLM
  sees the same JSON shape that the API itself emits, which keeps prompts
  small and predictable.
"""

from __future__ import annotations

import os
from typing import Any

from agent_identity_registry import (
    AgentNotFoundError,
    AIRClient,
    AirError,
    RateLimitedError,
)
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("air")

_client: AIRClient | None = None


def _get_client() -> AIRClient:
    """Lazily build a shared AIRClient. Created on first tool call, reused after."""
    global _client
    if _client is None:
        _client = AIRClient(
            base_url=os.environ.get("AIR_BASE_URL", "https://agentidentityregistry.org"),
            timeout=float(os.environ.get("AIR_TIMEOUT", "30")),
        )
    return _client


def _err(e: AirError, **extra: Any) -> dict[str, Any]:
    """Pack an AirError into an LLM-readable dict.

    Includes status_code so the LLM can distinguish "agent doesn't exist"
    (404) from "registry is down" (5xx) and recover differently.
    """
    payload: dict[str, Any] = {
        "error": str(e),
        "status_code": e.status_code,
        "error_class": type(e).__name__,
    }
    payload.update(extra)
    if isinstance(e, RateLimitedError):
        payload["retry_after_seconds"] = e.retry_after_seconds
    return payload


# ============================================================
# TOOLS — all read-only (per MCP architecture decision)
# ============================================================


@mcp.tool()
async def air_health() -> dict[str, Any]:
    """Check that the AIR registry is reachable and reports its version.

    Use this first when diagnosing whether a downstream lookup failure
    is the registry being down vs the specific agent being unknown.
    """
    client = _get_client()
    try:
        result = await client.get_health()
    except AirError as e:
        return _err(e)
    return result.model_dump(mode="json")


@mcp.tool()
async def air_list_agents(limit: int = 20, offset: int = 0) -> dict[str, Any]:
    """List registered agents, sorted by trust score descending.

    Args:
        limit: Max agents to return (1-100, default 20).
        offset: Pagination offset, default 0.

    Returns dict with `agents`, `total`, `limit`, `offset`.
    """
    client = _get_client()
    try:
        result = await client.list_agents(limit=limit, offset=offset)
    except AirError as e:
        return _err(e)
    return result.model_dump(mode="json")


@mcp.tool()
async def air_lookup_agent(air_id: str) -> dict[str, Any]:
    """Get the full record for one agent by AIR ID.

    Args:
        air_id: Format `AIR-XXXX-XXXX-XXXX` (Crockford base32 segments).

    Returns the agent's name, description, creator, capabilities, trust
    score, and verification state. Returns `{"error": ..., "status_code": 404}`
    if no agent with that ID exists.
    """
    client = _get_client()
    try:
        result = await client.get_agent(air_id)
    except AgentNotFoundError as e:
        return _err(e, air_id=air_id)
    except AirError as e:
        return _err(e)
    return result.model_dump(mode="json")


@mcp.tool()
async def air_trust_score(air_id: str) -> dict[str, Any]:
    """Get the 5-component trust-score breakdown for an agent.

    Components (each 0-1000, weighted into total): provenance (0.25),
    behavioral (0.25), transparency (0.20), security (0.15),
    peer_attestations (0.15). Grade: AAA / AA / A / BBB / BB / B / C.

    Use when you want to know WHY an agent has a given trust grade, not
    just the headline number — the components show what the agent does or
    doesn't have going for it.
    """
    client = _get_client()
    try:
        result = await client.get_trust_score(air_id)
    except AgentNotFoundError as e:
        return _err(e, air_id=air_id)
    except AirError as e:
        return _err(e)
    return result.model_dump(mode="json")


@mcp.tool()
async def air_did_document(air_id: str) -> dict[str, Any]:
    """Get the W3C DID Core JSON-LD document for an agent.

    Returns `id` (did:wba), `verificationMethod` (Ed25519 publicKeyMultibase),
    `authentication`, `assertionMethod`, and `service` endpoints. Use this
    when you need to verify a signature an agent produced, or when you need
    the agent's public key for any cryptographic interaction.

    Returns `{"error": ..., "status_code": 404}` if the agent has no
    public_key on file (registration without one means no key to publish).
    """
    client = _get_client()
    try:
        result = await client.get_did_document(air_id)
    except AgentNotFoundError as e:
        return _err(e, air_id=air_id)
    except AirError as e:
        return _err(e)
    return result.model_dump(mode="json", by_alias=True)


@mcp.tool()
async def air_check_name(name: str) -> dict[str, Any]:
    """Check whether an agent with this name already exists.

    Returns `{name, exists, count, existing_agents: [{air_id, name}]}`.
    AIR allows duplicate names (each agent gets a unique AIR ID regardless),
    but this is useful pre-registration if the caller wants to choose
    a distinct name.
    """
    client = _get_client()
    try:
        result = await client.check_name(name)
    except AirError as e:
        return _err(e)
    return result.model_dump(mode="json")
