"""Tests for the CLI entry point (python -m air_mcp / air-mcp-server)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

import air_mcp.__main__ as main_mod
from air_mcp.server import mcp


@pytest.fixture
def patched_run(monkeypatch):
    """Replace mcp.run with a recorder so main() doesn't actually start a server."""
    runs: list[dict] = []

    def fake_run(*, transport: str) -> None:
        runs.append({"transport": transport, "port": mcp.settings.port})

    monkeypatch.setattr(mcp, "run", fake_run)
    return runs


def test_default_transport_is_stdio(patched_run, monkeypatch):
    monkeypatch.setattr("sys.argv", ["air-mcp-server"])
    assert main_mod.main() == 0
    assert patched_run == [{"transport": "stdio", "port": mcp.settings.port}]


def test_streamable_http_with_explicit_port(patched_run, monkeypatch):
    monkeypatch.setattr(
        "sys.argv",
        ["air-mcp-server", "--transport", "streamable-http", "--port", "9090"],
    )
    assert main_mod.main() == 0
    assert patched_run[0]["transport"] == "streamable-http"
    assert patched_run[0]["port"] == 9090


def test_streamable_http_default_port_is_8080(patched_run, monkeypatch):
    monkeypatch.setattr(
        "sys.argv",
        ["air-mcp-server", "--transport", "streamable-http"],
    )
    assert main_mod.main() == 0
    assert patched_run[0]["port"] == 8080


def test_invalid_transport_rejected(monkeypatch):
    """argparse should reject anything outside the choices set."""
    monkeypatch.setattr("sys.argv", ["air-mcp-server", "--transport", "websocket"])
    with pytest.raises(SystemExit) as ei:
        main_mod.main()
    assert ei.value.code == 2  # argparse exit code for usage errors
