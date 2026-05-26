# air-mcp-server

[Model Context Protocol](https://modelcontextprotocol.io) server for the [Agent Identity Registry (AIR)](https://agentidentityregistry.org).

Drop into any MCP-aware LLM client (Claude Code, Cursor, Codex, etc.) and your agent can look up identities, trust scores, and W3C DID documents from the AIR registry — no SDK install required by the LLM client.

## v0.1 — Read-only

Six tools, all read-only. Write operations (register, update) require an `agent_secret` whose handling crosses the LLM context, which is a sharper design decision that deserves its own release. See `air/mcp-server-architecture-decision` for the full reasoning.

| Tool | What it does |
|------|--------------|
| `air_health` | Registry liveness check |
| `air_list_agents` | Paginated list of agents, sorted by trust score |
| `air_lookup_agent` | Full record for one agent by AIR ID |
| `air_trust_score` | 5-component trust-score breakdown |
| `air_did_document` | W3C DID Core JSON-LD with publicKeyMultibase |
| `air_check_name` | Is this name already taken? |

## Install

```bash
pip install air-mcp-server
```

Requires Python 3.10+.

## Use with Claude Code

Add to your Claude Code MCP config (typically `~/.claude/mcp.json` or project `.mcp.json`):

```json
{
  "mcpServers": {
    "air": {
      "command": "air-mcp-server"
    }
  }
}
```

Or use `python -m`:

```json
{
  "mcpServers": {
    "air": {
      "command": "python",
      "args": ["-m", "air_mcp"]
    }
  }
}
```

Then in any Claude Code session: "look up agent AIR-7F3K-M9JQ-X2PL in AIR" or "what's the trust score for DataProcessor-v3" and Claude will invoke the right tool.

## Configure

| Env var | Default | Purpose |
|---------|---------|---------|
| `AIR_BASE_URL` | `https://agentidentityregistry.org` | Point at a different registry (staging, local dev) |
| `AIR_TIMEOUT` | `30` | Per-request HTTP timeout in seconds |

## Transports

stdio (default — used by Claude Code, Cursor, Codex):

```bash
air-mcp-server
```

Streamable-HTTP (for remote MCP clients):

```bash
air-mcp-server --transport streamable-http --port 8080
```

## License

Apache 2.0.
