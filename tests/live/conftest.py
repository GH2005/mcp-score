"""Fixtures for the live MuseScore test suite.

These tests exercise the real WebSocket bridge served by the
mcp-score-bridge plugin inside a running MuseScore instance. They are
excluded from the default pytest run (see ``addopts`` in pyproject.toml)
and selected with ``pytest -m live``.

State doctrine: the suite treats the open score as a shared, mutable,
disposable resource. Every mutating test allocates fresh scratch measures
at the end of the score (``scratch`` fixture) and asserts a delta-scoped
MusicXML diff, so a dirty baseline never causes false failures. Undo is
never used for cleanup.
"""

from __future__ import annotations

import itertools
import os
import socket
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from mcp_score.bridge import get_musescore_bridge, set_active_bridge
from tests.live import mxl

if TYPE_CHECKING:
    from mcp_score.bridge.musescore import MuseScoreBridge

BRIDGE_HOST = "localhost"
BRIDGE_PORT = 8765
BRIDGE_URI = f"ws://{BRIDGE_HOST}:{BRIDGE_PORT}"
ARTIFACTS_DIR = Path(__file__).resolve().parent / "artifacts"

_snapshot_counter = itertools.count()

SnapshotFn = Callable[[str], Awaitable[mxl.Snapshot]]
ScratchFn = Callable[[int], Awaitable[tuple[int, int]]]


def _bridge_reachable() -> bool:
    try:
        with socket.create_connection((BRIDGE_HOST, BRIDGE_PORT), timeout=2.0):
            return True
    except OSError:
        return False


def pytest_collection_modifyitems(items: list[Any]) -> None:
    """Mark everything under tests/live with the live marker.

    The anyio marker cannot be added dynamically here -- anyio's fixture
    handling would not see it -- so each test module declares
    ``pytestmark = pytest.mark.anyio`` explicitly.
    """
    live_dir = str(Path(__file__).resolve().parent)
    for item in items:
        item_path = str(getattr(item, "path", ""))
        if item_path.startswith(live_dir):
            item.add_marker(pytest.mark.live)


@pytest.fixture(scope="session")
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture(scope="session", autouse=True)
def _require_live_bridge() -> None:
    if not _bridge_reachable():
        pytest.skip(
            f"MuseScore bridge not reachable on {BRIDGE_URI} -- start "
            "MuseScore with the mcp-score-bridge plugin running"
        )


@pytest.fixture(scope="session")
async def bridge(_require_live_bridge: None) -> AsyncIterator[MuseScoreBridge]:
    """The shared, connected MuseScore bridge (also set as active bridge)."""
    b = get_musescore_bridge()
    if not b.is_connected:
        connected = await b.connect()
        assert connected, f"Could not connect to the MuseScore bridge at {BRIDGE_URI}"
    set_active_bridge(b)
    yield b
    set_active_bridge(None)
    await b.disconnect()


@pytest.fixture(scope="session", autouse=True)
async def _score_guard(bridge: MuseScoreBridge) -> None:
    """Refuse to mutate a score that does not look disposable."""
    if os.environ.get("MCP_SCORE_LIVE_ANY_SCORE") == "1":
        return
    reply = await bridge.get_score()
    title = str((reply.get("result") or {}).get("title") or "")
    lowered = title.lower()
    if title and not any(tag in lowered for tag in ("untitled", "scratch", "mcp")):
        pytest.exit(
            f"Refusing to run the live suite against score titled {title!r}. "
            "The suite mutates the open score heavily. Open a disposable "
            "score or set MCP_SCORE_LIVE_ANY_SCORE=1 to override.",
            returncode=3,
        )


@pytest.fixture(scope="session")
def snapshot(bridge: MuseScoreBridge) -> SnapshotFn:
    """Export the live score via exportScore and parse it as ground truth."""
    ARTIFACTS_DIR.mkdir(exist_ok=True)

    async def _snap(label: str = "snap") -> mxl.Snapshot:
        index = next(_snapshot_counter)
        path = ARTIFACTS_DIR / f"{label}-{index:03d}.musicxml"
        reply = await bridge.send_command(
            "exportScore",
            {"path": path.as_posix(), "format": "musicxml"},
        )
        result = reply.get("result")
        assert isinstance(result, dict) and result.get("written") is True, (
            f"exportScore failed: {reply}"
        )
        return mxl.parse_snapshot(path)

    return _snap


@pytest.fixture()
def scratch(bridge: MuseScoreBridge) -> ScratchFn:
    """Append fresh scratch measures; return their 1-indexed inclusive range.

    Allocation happens at call time (not collection time) so earlier tests
    changing the measure count can never invalidate the range.
    """

    async def _alloc(count: int = 1) -> tuple[int, int]:
        info = await bridge.get_score()
        measure_count = int(info["result"]["measureCount"])
        reply = await bridge.append_measures(count)
        assert "result" in reply, f"appendMeasures failed: {reply}"
        return measure_count + 1, measure_count + count

    return _alloc


@pytest.fixture()
def no_active_bridge(bridge: MuseScoreBridge) -> Iterator[None]:
    """Temporarily clear the active bridge (for NOT_CONNECTED tests)."""
    set_active_bridge(None)
    yield
    set_active_bridge(bridge)


@pytest.fixture()
async def restore_musescore_connection(
    bridge: MuseScoreBridge,
) -> AsyncIterator[None]:
    """Restore the MuseScore connection and active bridge after a test that
    may disconnect it (e.g. connect_to_dorico disconnects the active bridge
    before attempting its own connection)."""
    original_host, original_port = bridge.host, bridge.port
    yield
    bridge.host, bridge.port = original_host, original_port
    if not bridge.is_connected:
        assert await bridge.connect()
    set_active_bridge(bridge)
