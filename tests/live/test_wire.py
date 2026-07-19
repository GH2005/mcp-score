"""Wire-protocol tests against the raw WebSocket (no bridge client)."""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING, Any

import pytest
import websockets

from tests.live.conftest import BRIDGE_URI

if TYPE_CHECKING:
    from mcp_score.bridge.musescore import MuseScoreBridge

pytestmark = pytest.mark.anyio


async def _roundtrip(payload: str) -> dict[str, Any]:
    async with websockets.connect(BRIDGE_URI) as ws:
        await ws.send(payload)
        raw = await asyncio.wait_for(ws.recv(), timeout=10)
        assert isinstance(raw, str)
        return json.loads(raw)


async def test_invalid_json_returns_error() -> None:
    reply = await _roundtrip("this is not json")
    assert "error" in reply
    assert "Invalid JSON" in reply["error"]


async def test_missing_command_field_returns_error() -> None:
    reply = await _roundtrip(json.dumps({"params": {}}))
    assert reply == {"error": "Missing 'command' field"}


async def test_unknown_command_returns_error() -> None:
    reply = await _roundtrip(json.dumps({"command": "noSuchCommand"}))
    assert reply == {"error": "Unknown command: noSuchCommand"}


async def test_second_client_gets_own_reply_without_crosstalk(
    bridge: MuseScoreBridge,
) -> None:
    """Two simultaneous clients: each request is answered on its own socket."""
    async with (
        websockets.connect(BRIDGE_URI) as idle,
        websockets.connect(BRIDGE_URI) as active,
    ):
        await active.send(json.dumps({"command": "ping"}))
        raw = await asyncio.wait_for(active.recv(), timeout=10)
        assert isinstance(raw, str)
        assert json.loads(raw) == {"result": "pong"}
        # The idle client must not receive the other client's reply.
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(idle.recv(), timeout=1.0)
    # The session bridge still works alongside the raw clients.
    assert await bridge.ping() is True
