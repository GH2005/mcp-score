"""WebSocket client for the MuseScore plugin bridge."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from typing import TYPE_CHECKING, Any

import websockets

from mcp_score.bridge.base import ScoreBridge

if TYPE_CHECKING:
    from websockets.asyncio.client import ClientConnection

__all__ = ["DEFAULT_PORT", "MuseScoreBridge"]

logger = logging.getLogger(__name__)

#: Default WebSocket port for the MuseScore QML plugin.
DEFAULT_PORT = 8765


class MuseScoreBridge(ScoreBridge):
    """WebSocket client for communicating with the MuseScore QML plugin.

    The QML plugin runs inside MuseScore and exposes a WebSocket server.
    This client sends commands and receives responses.
    """

    #: Timeout in seconds for receiving a response from MuseScore.
    RECV_TIMEOUT: float = 30.0

    def __init__(self, host: str = "localhost", port: int = DEFAULT_PORT) -> None:
        self.host = host
        self.port = port
        self._connection: ClientConnection | None = None

    @property
    def application_name(self) -> str:
        """Human-readable application name."""
        return "MuseScore"

    @property
    def uri(self) -> str:
        """WebSocket URI."""
        return f"ws://{self.host}:{self.port}"

    async def connect(self) -> bool:
        """Connect to the MuseScore WebSocket server.

        Returns:
            True if connected successfully, False otherwise.
        """
        try:
            self._connection = await websockets.connect(self.uri)
            logger.info("Connected to MuseScore at %s", self.uri)
            return True
        except (OSError, websockets.exceptions.WebSocketException) as exception:
            logger.error(
                "Failed to connect to MuseScore at %s: %s", self.uri, exception
            )
            self._connection = None
            return False

    async def disconnect(self) -> None:
        """Close the WebSocket connection."""
        if self._connection is not None:
            with contextlib.suppress(websockets.exceptions.WebSocketException, OSError):
                await self._connection.close()
            self._connection = None
            logger.info("Disconnected from MuseScore")

    async def _send_raw(self, command_json: str) -> dict[str, Any]:
        """Send a raw JSON command string over the active connection."""
        connection = self._connection
        if connection is None:
            return {"error": "No active connection"}

        await connection.send(command_json)
        response_raw = await asyncio.wait_for(
            connection.recv(), timeout=self.RECV_TIMEOUT
        )
        if not isinstance(response_raw, str):
            return {"error": "Received non-text response from MuseScore"}
        logger.debug("Received: %s", response_raw)
        try:
            result: dict[str, Any] = json.loads(response_raw)
        except json.JSONDecodeError as exception:
            return {"error": f"Invalid JSON from MuseScore: {exception}"}
        return result

    async def send_command(
        self, action: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Send a command to MuseScore and return the response.

        Auto-connects if not already connected. Attempts one reconnect
        on connection failure.

        Args:
            action: Command action name (e.g. "getScore", "addNote").
            params: Optional command parameters.

        Returns:
            Parsed JSON response from MuseScore.
        """
        if self._connection is None and not await self.connect():
            return {"error": f"Cannot connect to MuseScore at {self.uri}"}

        command: dict[str, Any] = {"command": action}
        if params is not None:
            command["params"] = params

        command_json = json.dumps(command)
        logger.debug("Sending: %s", command_json)

        try:
            return await self._send_raw(command_json)
        except (
            websockets.exceptions.ConnectionClosed,
            websockets.exceptions.WebSocketException,
            TimeoutError,
        ):
            logger.warning("Connection lost, attempting reconnect...")
            with contextlib.suppress(websockets.exceptions.WebSocketException, OSError):
                if self._connection is not None:
                    await self._connection.close()
            self._connection = None
            if not await self.connect():
                return {"error": "Lost connection to MuseScore and reconnect failed"}

            # Retry the command once after reconnecting.
            try:
                return await self._send_raw(command_json)
            except Exception as exception:  # noqa: BLE001
                return {"error": f"Command failed after reconnect: {exception}"}

    async def ping(self) -> bool:
        """Check if the connection is alive."""
        result = await self.send_command("ping")
        return result.get("result") == "pong"

    # ── Convenience methods ──────────────────────────────────────────

    async def get_score(self) -> dict[str, Any]:
        """Get the current score information."""
        return await self.send_command("getScore")

    async def get_cursor_info(self) -> dict[str, Any]:
        """Get current cursor position info."""
        return await self.send_command("getCursorInfo")

    async def get_properties(self) -> dict[str, Any]:
        """Get properties of the current selection.

        Returns cursor info as MuseScore's equivalent of selection properties.
        """
        return await self.get_cursor_info()

    async def go_to_measure(self, measure: int) -> dict[str, Any]:
        """Navigate to a specific measure (1-indexed)."""
        return await self.send_command("goToMeasure", {"measure": measure})

    async def go_to_staff(self, staff: int, voice: int | None = None) -> dict[str, Any]:
        """Navigate to a specific staff (0-indexed) and optionally a voice.

        Args:
            staff: Staff index (0-indexed).
            voice: Voice within the staff (0-3). ``None`` keeps the
                current voice.
        """
        params: dict[str, Any] = {"staff": staff}
        if voice is not None:
            params["voice"] = voice
        return await self.send_command("goToStaff", params)

    async def add_note(
        self,
        pitch: int,
        duration: dict[str, int],
        advance_cursor: bool = True,
        add_to_chord: bool = False,
        tpc: int | None = None,
    ) -> dict[str, Any]:
        """Add a note at the current cursor position.

        Args:
            pitch: MIDI pitch (0-127).
            duration: ``{"numerator": n, "denominator": d}``.
            advance_cursor: Move the cursor past the note afterwards.
            add_to_chord: Stack onto the previous note instead of
                advancing, building a chord.
            tpc: MuseScore tonal pitch class -- the note's spelling. Send
                it whenever the spelling matters: without it MuseScore
                guesses from the key signature. See
                :func:`mcp_score.theory.name_to_pitch_tpc`.
        """
        params: dict[str, Any] = {
            "pitch": pitch,
            "duration": duration,
            "advanceCursorAfterAction": advance_cursor,
        }
        if add_to_chord:
            params["addToChord"] = True
        if tpc is not None:
            params["tpc"] = tpc
        return await self.send_command("addNote", params)

    async def add_rest(
        self,
        duration: dict[str, int],
        advance_cursor: bool = True,
    ) -> dict[str, Any]:
        """Add a rest at the current cursor position."""
        return await self.send_command(
            "addRest",
            {
                "duration": duration,
                "advanceCursorAfterAction": advance_cursor,
            },
        )

    async def set_pitches(
        self,
        staff: int,
        voice: int,
        start_measure: int,
        end_measure: int,
        edits: list[dict[str, int]],
    ) -> dict[str, Any]:
        """Rewrite the pitch and spelling of notes already in the score.

        Each edit is ``{"oldPitch": int, "newPitch": int, "newTpc": int}``
        and applies positionally: edit N addresses the Nth note of the
        staff+voice across the measure range, ordered by tick and then by
        ascending pitch within a chord. The plugin verifies every
        ``oldPitch`` before writing anything, so a request built from a
        stale snapshot fails whole instead of half-applying.

        ``newTpc`` is required alongside ``newPitch``: MuseScore exports a
        note's spelling rather than its MIDI number, so changing one
        without the other produces a note that still exports as the old
        pitch.
        """
        return await self.send_command(
            "setPitches",
            {
                "staff": staff,
                "voice": voice,
                "startMeasure": start_measure,
                "endMeasure": end_measure,
                "edits": edits,
            },
        )

    async def add_rehearsal_mark(self, text: str) -> dict[str, Any]:
        """Add a rehearsal mark at the current cursor position."""
        return await self.send_command("addRehearsalMark", {"text": text})

    async def set_barline(self, barline_type: str) -> dict[str, Any]:
        """Set a barline at the current cursor position."""
        return await self.send_command("setBarline", {"type": barline_type})

    async def set_key_signature(self, fifths: int) -> dict[str, Any]:
        """Set the key signature (positive = sharps, negative = flats)."""
        return await self.send_command("setKeySignature", {"fifths": fifths})

    async def set_time_signature(
        self, numerator: int, denominator: int
    ) -> dict[str, Any]:
        """Set the time signature."""
        return await self.send_command(
            "setTimeSignature",
            {"numerator": numerator, "denominator": denominator},
        )

    async def set_tempo(self, bpm: int, text: str | None = None) -> dict[str, Any]:
        """Set the tempo."""
        params: dict[str, Any] = {"bpm": bpm}
        if text is not None:
            params["text"] = text
        return await self.send_command("setTempo", params)

    async def add_chord_symbol(self, text: str) -> dict[str, Any]:
        """Add a chord symbol at the current cursor position."""
        return await self.send_command("addChordSymbol", {"text": text})

    async def add_dynamic(self, dynamic_type: str) -> dict[str, Any]:
        """Add a dynamic marking at the current cursor position."""
        return await self.send_command("addDynamic", {"type": dynamic_type})

    async def append_measures(self, count: int = 1) -> dict[str, Any]:
        """Append measures to the end of the score."""
        return await self.send_command("appendMeasures", {"count": count})

    async def process_sequence(self, commands: list[dict[str, Any]]) -> dict[str, Any]:
        """Execute a sequence of commands atomically."""
        return await self.send_command("processSequence", {"sequence": commands})

    async def export_score(
        self, path: str, export_format: str = "musicxml"
    ) -> dict[str, Any]:
        """Snapshot the live in-memory score to disk via the plugin.

        Captures unsaved edits without touching the user's own file. The
        path should be absolute with forward slashes.
        """
        return await self.send_command(
            "exportScore", {"path": path, "format": export_format}
        )

    async def undo(self) -> dict[str, Any]:
        """Undo the last action."""
        return await self.send_command("undo")
