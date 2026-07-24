"""MCP tool definitions for live score interaction."""

import json
import tempfile
import uuid
from pathlib import Path
from typing import Any

from mcp_score.bridge import ScoreBridge, get_active_bridge
from mcp_score.bridge.musescore import MuseScoreBridge
from mcp_score.musicxml import Snapshot, parse_snapshot

__all__ = [
    "NOT_CONNECTED",
    "PLUGIN_OUTDATED_ERROR",
    "check_measure",
    "connected_bridge",
    "export_dir",
    "export_snapshot",
    "to_json",
]

NOT_CONNECTED = (
    "Not connected to any score application. "
    "Use connect_to_musescore, connect_to_dorico, or "
    "connect_to_sibelius first."
)

PLUGIN_OUTDATED_ERROR = (
    "The installed mcp-score-bridge plugin does not support the exportScore "
    "command. Reinstall it with 'mcp-score install-plugin' and restart "
    "MuseScore."
)


def to_json(data: dict[str, Any]) -> str:
    """Serialize a result dict to a JSON string for MCP tool responses."""
    return json.dumps(data)


def connected_bridge() -> ScoreBridge | None:
    """Return the active bridge if connected, or ``None``.

    Tools that require an active connection should call this and return
    an error when ``None`` is returned::

        bridge = connected_bridge()
        if bridge is None:
            return to_json({"error": NOT_CONNECTED})
    """
    bridge = get_active_bridge()
    if bridge is None:
        return None
    return bridge if bridge.is_connected else None


def check_measure(measure: int, name: str = "measure") -> str | None:
    """Return an error JSON string if *measure* is < 1, else ``None``."""
    if measure < 1:
        return to_json({"error": f"{name} must be >= 1."})
    return None


def export_dir() -> Path:
    """Directory holding throwaway score snapshots."""
    directory = Path(tempfile.gettempdir()) / "mcp-score-exports"
    directory.mkdir(exist_ok=True)
    return directory


async def export_snapshot(
    bridge: MuseScoreBridge,
) -> tuple[Snapshot | None, str | None]:
    """Snapshot the live score to a temp file and parse it.

    This is the ground-truth read: MuseScore serializes its own in-memory
    score to MusicXML and music21 parses it, so chords, voices and
    annotations the cursor API cannot see are all reported.

    Returns:
        ``(snapshot, None)`` on success or ``(None, error message)``.
    """
    path = export_dir() / f"read-{uuid.uuid4().hex}.musicxml"
    reply = await bridge.export_score(path.as_posix(), "musicxml")
    if "error" in reply:
        error = str(reply["error"])
        if "Unknown command" in error:
            return None, PLUGIN_OUTDATED_ERROR
        return None, error
    result = reply.get("result")
    if not isinstance(result, dict) or result.get("written") is not True:
        return None, f"exportScore did not write a file: {reply}"
    try:
        return parse_snapshot(path), None
    finally:
        path.unlink(missing_ok=True)
