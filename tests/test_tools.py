"""Tests for MCP tool modules — validation, helpers, and tool behavior."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

from mcp_score.bridge.musescore import MuseScoreBridge
from mcp_score.tools import (
    NOT_CONNECTED,
    check_measure,
    connected_bridge,
)


def _write_fixture_musicxml(path: str) -> dict[str, object]:
    """Write a tiny 2-measure score (C4+E4, then G4) as MusicXML fixture."""
    from music21 import meter, note, stream

    part = stream.Part()
    first = stream.Measure(number=1)
    first.append(meter.TimeSignature("4/4"))
    first.append(note.Note("C4", quarterLength=1.0))
    first.append(note.Note("E4", quarterLength=1.0))
    second = stream.Measure(number=2)
    second.append(note.Note("G4", quarterLength=2.0))
    part.append(first)
    part.append(second)
    score = stream.Score()
    score.append(part)
    score.write("musicxml", fp=path)
    return {"result": {"written": True, "path": path, "format": "musicxml"}}


def _musescore_bridge_with_fixture_export() -> AsyncMock:
    """A MuseScore-typed mock whose export_score writes the fixture score."""
    mock_bridge = AsyncMock(spec=MuseScoreBridge)
    mock_bridge.is_connected = True
    mock_bridge.export_score = AsyncMock(
        side_effect=lambda path, fmt="musicxml": _write_fixture_musicxml(path)
    )
    return mock_bridge


# ── Helper tests ─────────────────────────────────────────────────────


class TestCheckMeasure:
    def test_valid_measure_returns_none(self) -> None:
        assert check_measure(1) is None

    def test_invalid_measure_returns_error(self) -> None:
        result = check_measure(0)
        assert result is not None
        assert "must be >= 1" in result


class TestConnectedBridge:
    def test_get_connected_bridge_returns_bridge(self) -> None:
        # Arrange
        mock_bridge = AsyncMock()
        mock_bridge.is_connected = True

        with patch("mcp_score.tools.get_active_bridge", return_value=mock_bridge):
            # Act
            result = connected_bridge()

        # Assert
        assert result is mock_bridge

    def test_get_disconnected_bridge_returns_none(self) -> None:
        # Arrange
        mock_bridge = AsyncMock()
        mock_bridge.is_connected = False

        with patch("mcp_score.tools.get_active_bridge", return_value=mock_bridge):
            # Act
            result = connected_bridge()

        # Assert
        assert result is None

    def test_get_bridge_without_active_returns_none(self) -> None:
        # Arrange / Act
        with patch("mcp_score.tools.get_active_bridge", return_value=None):
            result = connected_bridge()

        # Assert
        assert result is None


# ── Connection tool tests ────────────────────────────────────────────


class TestConnectToMusescore:
    @pytest.mark.anyio()
    async def test_connect_returns_success(self) -> None:
        # Arrange
        from mcp_score.tools.connection import connect_to_musescore

        mock_bridge = AsyncMock()
        mock_bridge.connect = AsyncMock(return_value=True)
        mock_bridge.is_connected = False

        with (
            patch(
                "mcp_score.tools.connection.get_musescore_bridge",
                return_value=mock_bridge,
            ),
            patch(
                "mcp_score.tools.connection.get_active_bridge",
                return_value=None,
            ),
            patch("mcp_score.tools.connection.set_active_bridge"),
        ):
            # Act
            result = json.loads(await connect_to_musescore())

        # Assert
        assert result["success"] is True
        assert "Connected" in result["message"]

    @pytest.mark.anyio()
    async def test_connect_failure_returns_error(self) -> None:
        # Arrange
        from mcp_score.tools.connection import connect_to_musescore

        mock_bridge = AsyncMock()
        mock_bridge.connect = AsyncMock(return_value=False)
        mock_bridge.is_connected = False

        with (
            patch(
                "mcp_score.tools.connection.get_musescore_bridge",
                return_value=mock_bridge,
            ),
            patch(
                "mcp_score.tools.connection.get_active_bridge",
                return_value=None,
            ),
        ):
            # Act
            result = json.loads(await connect_to_musescore())

        # Assert
        assert "error" in result
        assert "Could not connect" in result["error"]


class TestDisconnectFromMusescore:
    @pytest.mark.anyio()
    async def test_disconnect_returns_success(self) -> None:
        # Arrange
        from mcp_score.tools.connection import disconnect_from_musescore

        mock_bridge = AsyncMock()

        with (
            patch(
                "mcp_score.tools.connection.get_musescore_bridge",
                return_value=mock_bridge,
            ),
            patch(
                "mcp_score.tools.connection.get_active_bridge",
                return_value=mock_bridge,
            ),
            patch("mcp_score.tools.connection.set_active_bridge"),
        ):
            # Act
            result = json.loads(await disconnect_from_musescore())

        # Assert
        assert result["success"] is True
        mock_bridge.disconnect.assert_called_once()


class TestGetLiveScoreInfo:
    @pytest.mark.anyio()
    async def test_get_info_without_connection_returns_error(self) -> None:
        # Arrange
        from mcp_score.tools.connection import get_live_score_info

        with patch("mcp_score.tools.get_active_bridge", return_value=None):
            # Act
            result = json.loads(await get_live_score_info())

        # Assert
        assert "error" in result
        assert NOT_CONNECTED in result["error"]

    @pytest.mark.anyio()
    async def test_get_info_returns_score_data(self) -> None:
        # Arrange
        from mcp_score.tools.connection import get_live_score_info

        mock_bridge = AsyncMock()
        mock_bridge.is_connected = True
        mock_bridge.get_score = AsyncMock(
            return_value={"title": "Test Score", "measures": 32}
        )

        with patch("mcp_score.tools.get_active_bridge", return_value=mock_bridge):
            # Act
            result = json.loads(await get_live_score_info())

        # Assert
        assert result["title"] == "Test Score"


class TestPingScoreApp:
    @pytest.mark.anyio()
    async def test_ping_without_connection_returns_error(self) -> None:
        # Arrange
        from mcp_score.tools.connection import ping_score_app

        with patch("mcp_score.tools.get_active_bridge", return_value=None):
            # Act
            result = json.loads(await ping_score_app())

        # Assert
        assert "error" in result

    @pytest.mark.anyio()
    async def test_ping_responsive_app_returns_success(self) -> None:
        # Arrange
        from mcp_score.tools.connection import ping_score_app

        mock_bridge = AsyncMock()
        mock_bridge.is_connected = True
        mock_bridge.ping = AsyncMock(return_value=True)
        mock_bridge.application_name = "MuseScore"

        with patch("mcp_score.tools.get_active_bridge", return_value=mock_bridge):
            # Act
            result = json.loads(await ping_score_app())

        # Assert
        assert result["success"] is True

    @pytest.mark.anyio()
    async def test_ping_unresponsive_app_returns_error(self) -> None:
        # Arrange
        from mcp_score.tools.connection import ping_score_app

        mock_bridge = AsyncMock()
        mock_bridge.is_connected = True
        mock_bridge.ping = AsyncMock(return_value=False)
        mock_bridge.application_name = "MuseScore"

        with patch("mcp_score.tools.get_active_bridge", return_value=mock_bridge):
            # Act
            result = json.loads(await ping_score_app())

        # Assert
        assert "error" in result


# ── Analysis tool tests ──────────────────────────────────────────────


class TestReadPassage:
    @pytest.mark.anyio()
    async def test_read_passage_without_connection_returns_error(self) -> None:
        # Arrange
        from mcp_score.tools.analysis import read_passage

        with patch("mcp_score.tools.get_active_bridge", return_value=None):
            # Act
            result = json.loads(await read_passage(1, 4))

        # Assert
        assert "error" in result

    @pytest.mark.anyio()
    async def test_read_passage_with_invalid_start_returns_error(self) -> None:
        # Arrange
        from mcp_score.tools.analysis import read_passage

        mock_bridge = AsyncMock()
        mock_bridge.is_connected = True

        with patch("mcp_score.tools.get_active_bridge", return_value=mock_bridge):
            # Act
            result = json.loads(await read_passage(0, 4))

        # Assert
        assert "must be >= 1" in result["error"]

    @pytest.mark.anyio()
    async def test_read_passage_with_end_before_start_returns_error(self) -> None:
        # Arrange
        from mcp_score.tools.analysis import read_passage

        mock_bridge = AsyncMock()
        mock_bridge.is_connected = True

        with patch("mcp_score.tools.get_active_bridge", return_value=mock_bridge):
            # Act
            result = json.loads(await read_passage(5, 3))

        # Assert
        assert "end_measure" in result["error"]

    @pytest.mark.anyio()
    async def test_read_passage_returns_elements_for_range(self) -> None:
        # Arrange
        from mcp_score.tools.analysis import read_passage

        mock_bridge = AsyncMock()
        mock_bridge.is_connected = True
        mock_bridge.get_cursor_info = AsyncMock(return_value={"beat": 1})

        with patch("mcp_score.tools.get_active_bridge", return_value=mock_bridge):
            # Act
            result = json.loads(await read_passage(1, 3))

        # Assert
        assert result["success"] is True
        assert len(result["elements"]) == 3
        assert mock_bridge.go_to_measure.call_count == 3

    @pytest.mark.anyio()
    async def test_read_passage_musescore_reports_all_notes(self) -> None:
        # Arrange
        from mcp_score.tools.analysis import read_passage

        mock_bridge = _musescore_bridge_with_fixture_export()

        with patch("mcp_score.tools.get_active_bridge", return_value=mock_bridge):
            # Act
            result = json.loads(await read_passage(1, 2, staff=0))

        # Assert
        assert result["success"] is True
        assert len(result["elements"]) == 2
        first_events = result["elements"][0]["staves"]["0"]["events"]
        midis = [e["midi"] for e in first_events if e["kind"] != "rest"]
        assert [60] in midis and [64] in midis
        second_events = result["elements"][1]["staves"]["0"]["events"]
        second_midis = [e["midi"] for e in second_events if e["kind"] != "rest"]
        assert [67] in second_midis

    @pytest.mark.anyio()
    async def test_read_passage_musescore_invalid_staff_returns_error(self) -> None:
        # Arrange
        from mcp_score.tools.analysis import read_passage

        mock_bridge = _musescore_bridge_with_fixture_export()

        with patch("mcp_score.tools.get_active_bridge", return_value=mock_bridge):
            # Act
            result = json.loads(await read_passage(1, 2, staff=5))

        # Assert
        assert "staff must be one of" in result["error"]


class TestReadPassageWithStaff:
    @pytest.mark.anyio()
    async def test_read_passage_with_staff_navigates_to_staff(self) -> None:
        # Arrange
        from mcp_score.tools.analysis import read_passage

        mock_bridge = AsyncMock()
        mock_bridge.is_connected = True
        mock_bridge.get_cursor_info = AsyncMock(return_value={"beat": 1})

        with patch("mcp_score.tools.get_active_bridge", return_value=mock_bridge):
            # Act
            await read_passage(1, 2, staff=3)

        # Assert
        assert mock_bridge.go_to_staff.call_count == 2
        mock_bridge.go_to_staff.assert_called_with(3)

    @pytest.mark.anyio()
    async def test_read_passage_without_staff_skips_staff_navigation(self) -> None:
        # Arrange
        from mcp_score.tools.analysis import read_passage

        mock_bridge = AsyncMock()
        mock_bridge.is_connected = True
        mock_bridge.get_cursor_info = AsyncMock(return_value={"beat": 1})

        with patch("mcp_score.tools.get_active_bridge", return_value=mock_bridge):
            # Act
            await read_passage(1, 2, staff=None)

        # Assert
        mock_bridge.go_to_staff.assert_not_called()


class TestGetMeasureContent:
    @pytest.mark.anyio()
    async def test_get_measure_without_connection_returns_error(self) -> None:
        # Arrange
        from mcp_score.tools.analysis import get_measure_content

        with patch("mcp_score.tools.get_active_bridge", return_value=None):
            # Act
            result = json.loads(await get_measure_content(1))

        # Assert
        assert "error" in result

    @pytest.mark.anyio()
    async def test_get_measure_with_invalid_number_returns_error(self) -> None:
        # Arrange
        from mcp_score.tools.analysis import get_measure_content

        mock_bridge = AsyncMock()
        mock_bridge.is_connected = True

        with patch("mcp_score.tools.get_active_bridge", return_value=mock_bridge):
            # Act
            result = json.loads(await get_measure_content(0))

        # Assert
        assert "must be >= 1" in result["error"]

    @pytest.mark.anyio()
    async def test_get_measure_content_musescore_reads_from_export(self) -> None:
        # Arrange
        from mcp_score.tools.analysis import get_measure_content

        mock_bridge = _musescore_bridge_with_fixture_export()

        with patch("mcp_score.tools.get_active_bridge", return_value=mock_bridge):
            # Act
            result = json.loads(await get_measure_content(1, staff=0))

        # Assert
        assert result["success"] is True
        events = result["content"]["events"]
        midis = [e["midi"] for e in events if e["kind"] != "rest"]
        assert [60] in midis and [64] in midis

    @pytest.mark.anyio()
    async def test_get_measure_content_out_of_range_returns_error(self) -> None:
        # Arrange
        from mcp_score.tools.analysis import get_measure_content

        mock_bridge = _musescore_bridge_with_fixture_export()

        with patch("mcp_score.tools.get_active_bridge", return_value=mock_bridge):
            # Act
            result = json.loads(await get_measure_content(99))

        # Assert
        assert "out of range" in result["error"]

    @pytest.mark.anyio()
    async def test_get_measure_content_outdated_plugin_returns_hint(self) -> None:
        # Arrange
        from mcp_score.tools.analysis import get_measure_content

        mock_bridge = AsyncMock(spec=MuseScoreBridge)
        mock_bridge.is_connected = True
        mock_bridge.export_score = AsyncMock(
            return_value={"error": "Unknown command: exportScore"}
        )

        with patch("mcp_score.tools.get_active_bridge", return_value=mock_bridge):
            # Act
            result = json.loads(await get_measure_content(1))

        # Assert
        assert "install-plugin" in result["error"]


class TestExportLiveScore:
    @pytest.mark.anyio()
    async def test_export_without_connection_returns_error(self) -> None:
        # Arrange
        from mcp_score.tools.analysis import export_live_score

        with patch("mcp_score.tools.get_active_bridge", return_value=None):
            # Act
            result = json.loads(await export_live_score())

        # Assert
        assert "error" in result

    @pytest.mark.anyio()
    async def test_export_with_non_musescore_bridge_returns_error(self) -> None:
        # Arrange
        from mcp_score.tools.analysis import export_live_score

        mock_bridge = AsyncMock()
        mock_bridge.is_connected = True

        with patch("mcp_score.tools.get_active_bridge", return_value=mock_bridge):
            # Act
            result = json.loads(await export_live_score())

        # Assert
        assert "only supported with MuseScore" in result["error"]

    @pytest.mark.anyio()
    async def test_export_rejects_mscz(self) -> None:
        # Arrange
        from mcp_score.tools.analysis import export_live_score

        mock_bridge = AsyncMock(spec=MuseScoreBridge)
        mock_bridge.is_connected = True

        with patch("mcp_score.tools.get_active_bridge", return_value=mock_bridge):
            # Act
            result = json.loads(await export_live_score(format="mscz"))

        # Assert
        assert "broken" in result["error"]
        mock_bridge.export_score.assert_not_called()

    @pytest.mark.anyio()
    async def test_export_rejects_unknown_format(self) -> None:
        # Arrange
        from mcp_score.tools.analysis import export_live_score

        mock_bridge = AsyncMock(spec=MuseScoreBridge)
        mock_bridge.is_connected = True

        with patch("mcp_score.tools.get_active_bridge", return_value=mock_bridge):
            # Act
            result = json.loads(await export_live_score(format="docx"))

        # Assert
        assert "format must be one of" in result["error"]

    @pytest.mark.anyio()
    async def test_export_rejects_relative_path(self) -> None:
        # Arrange
        from mcp_score.tools.analysis import export_live_score

        mock_bridge = AsyncMock(spec=MuseScoreBridge)
        mock_bridge.is_connected = True

        with patch("mcp_score.tools.get_active_bridge", return_value=mock_bridge):
            # Act
            result = json.loads(await export_live_score(path="out.musicxml"))

        # Assert
        assert "absolute" in result["error"]

    @pytest.mark.anyio()
    async def test_export_happy_path_returns_target(self) -> None:
        # Arrange
        from mcp_score.tools.analysis import export_live_score

        mock_bridge = AsyncMock(spec=MuseScoreBridge)
        mock_bridge.is_connected = True
        mock_bridge.export_score = AsyncMock(return_value={"result": {"written": True}})

        with patch("mcp_score.tools.get_active_bridge", return_value=mock_bridge):
            # Act
            result = json.loads(
                await export_live_score(path="C:/tmp/snapshot.musicxml")
            )

        # Assert
        assert result["success"] is True
        assert result["path"] == "C:/tmp/snapshot.musicxml"
        mock_bridge.export_score.assert_called_once_with(
            "C:/tmp/snapshot.musicxml", "musicxml"
        )

    @pytest.mark.anyio()
    async def test_export_outdated_plugin_returns_hint(self) -> None:
        # Arrange
        from mcp_score.tools.analysis import export_live_score

        mock_bridge = AsyncMock(spec=MuseScoreBridge)
        mock_bridge.is_connected = True
        mock_bridge.export_score = AsyncMock(
            return_value={"error": "Unknown command: exportScore"}
        )

        with patch("mcp_score.tools.get_active_bridge", return_value=mock_bridge):
            # Act
            result = json.loads(await export_live_score())

        # Assert
        assert "install-plugin" in result["error"]


class TestGetSelectionProperties:
    @pytest.mark.anyio()
    async def test_get_properties_without_connection_returns_error(self) -> None:
        # Arrange
        from mcp_score.tools.analysis import get_selection_properties

        with patch("mcp_score.tools.get_active_bridge", return_value=None):
            # Act
            result = json.loads(await get_selection_properties())

        # Assert
        assert "error" in result
        assert NOT_CONNECTED in result["error"]

    @pytest.mark.anyio()
    async def test_get_properties_returns_selection_data(self) -> None:
        # Arrange
        from mcp_score.tools.analysis import get_selection_properties

        mock_bridge = AsyncMock()
        mock_bridge.is_connected = True
        mock_bridge.get_properties = AsyncMock(
            return_value={"Properties": [{"Name": "kNoteHideStem"}]}
        )

        with patch("mcp_score.tools.get_active_bridge", return_value=mock_bridge):
            # Act
            result = json.loads(await get_selection_properties())

        # Assert
        assert result["Properties"][0]["Name"] == "kNoteHideStem"


class TestTransposePassageErrorBranch:
    @pytest.mark.anyio()
    async def test_transpose_with_failed_selection_returns_error(self) -> None:
        # Arrange
        from mcp_score.tools.manipulation import transpose_passage

        mock_bridge = AsyncMock(spec=MuseScoreBridge)
        mock_bridge.is_connected = True
        mock_bridge.go_to_measure = AsyncMock(return_value={"result": "ok"})
        mock_bridge.go_to_staff = AsyncMock(return_value={"result": "ok"})
        mock_bridge.send_command = AsyncMock(return_value={"error": "Invalid range"})

        with patch("mcp_score.tools.get_active_bridge", return_value=mock_bridge):
            # Act
            result = json.loads(await transpose_passage(1, 4, 0, 5))

        # Assert — should return the error from selectCustomRange, not call transpose
        assert result["error"] == "Invalid range"
        assert mock_bridge.send_command.call_count == 1


# ── Manipulation tool tests ──────────────────────────────────────────


class TestManipulationToolsRequireConnection:
    """All manipulation tools must return an error when not connected."""

    @pytest.mark.anyio()
    async def test_add_rehearsal_mark_without_connection_returns_error(self) -> None:
        # Arrange
        from mcp_score.tools.manipulation import add_live_rehearsal_mark

        # Act
        with patch("mcp_score.tools.get_active_bridge", return_value=None):
            result = json.loads(await add_live_rehearsal_mark(1, "A"))

        # Assert
        assert "error" in result

    @pytest.mark.anyio()
    async def test_add_chord_symbol_without_connection_returns_error(self) -> None:
        # Arrange
        from mcp_score.tools.manipulation import add_live_chord_symbol

        # Act
        with patch("mcp_score.tools.get_active_bridge", return_value=None):
            result = json.loads(await add_live_chord_symbol(1, "Cmaj7"))

        # Assert
        assert "error" in result

    @pytest.mark.anyio()
    async def test_set_barline_without_connection_returns_error(self) -> None:
        # Arrange
        from mcp_score.tools.manipulation import set_live_barline

        # Act
        with patch("mcp_score.tools.get_active_bridge", return_value=None):
            result = json.loads(await set_live_barline(1, "double"))

        # Assert
        assert "error" in result

    @pytest.mark.anyio()
    async def test_set_tempo_without_connection_returns_error(self) -> None:
        # Arrange
        from mcp_score.tools.manipulation import set_live_tempo

        # Act
        with patch("mcp_score.tools.get_active_bridge", return_value=None):
            result = json.loads(await set_live_tempo(1, 120))

        # Assert
        assert "error" in result

    @pytest.mark.anyio()
    async def test_transpose_without_connection_returns_error(self) -> None:
        # Arrange
        from mcp_score.tools.manipulation import transpose_passage

        # Act
        with patch("mcp_score.tools.get_active_bridge", return_value=None):
            result = json.loads(await transpose_passage(1, 4, 0, 2))

        # Assert
        assert "error" in result

    @pytest.mark.anyio()
    async def test_undo_without_connection_returns_error(self) -> None:
        # Arrange
        from mcp_score.tools.manipulation import undo_last_action

        # Act
        with patch("mcp_score.tools.get_active_bridge", return_value=None):
            result = json.loads(await undo_last_action())

        # Assert
        assert "error" in result


class TestManipulationMeasureValidation:
    """Manipulation tools must reject invalid measure numbers."""

    @pytest.mark.anyio()
    async def test_add_rehearsal_mark_with_zero_measure_returns_error(self) -> None:
        # Arrange
        from mcp_score.tools.manipulation import add_live_rehearsal_mark

        mock_bridge = AsyncMock()
        mock_bridge.is_connected = True

        # Act
        with patch("mcp_score.tools.get_active_bridge", return_value=mock_bridge):
            result = json.loads(await add_live_rehearsal_mark(0, "A"))

        # Assert
        assert "must be >= 1" in result["error"]

    @pytest.mark.anyio()
    async def test_add_chord_symbol_with_negative_measure_returns_error(self) -> None:
        # Arrange
        from mcp_score.tools.manipulation import add_live_chord_symbol

        mock_bridge = AsyncMock()
        mock_bridge.is_connected = True

        # Act
        with patch("mcp_score.tools.get_active_bridge", return_value=mock_bridge):
            result = json.loads(await add_live_chord_symbol(-1, "Cmaj7"))

        # Assert
        assert "must be >= 1" in result["error"]

    @pytest.mark.anyio()
    async def test_transpose_with_end_before_start_returns_error(self) -> None:
        # Arrange
        from mcp_score.tools.manipulation import transpose_passage

        mock_bridge = AsyncMock(spec=MuseScoreBridge)
        mock_bridge.is_connected = True

        # Act
        with patch("mcp_score.tools.get_active_bridge", return_value=mock_bridge):
            result = json.loads(await transpose_passage(5, 3, 0, 2))

        # Assert
        assert "end_measure" in result["error"]


class TestManipulationHappyPaths:
    """Verify manipulation tools delegate correctly to the bridge."""

    @pytest.mark.anyio()
    async def test_add_rehearsal_mark_navigates_and_delegates(self) -> None:
        # Arrange
        from mcp_score.tools.manipulation import add_live_rehearsal_mark

        mock_bridge = AsyncMock()
        mock_bridge.is_connected = True
        mock_bridge.add_rehearsal_mark = AsyncMock(return_value={"result": "ok"})

        with patch("mcp_score.tools.get_active_bridge", return_value=mock_bridge):
            # Act
            result = json.loads(await add_live_rehearsal_mark(5, "B"))

        # Assert
        mock_bridge.go_to_measure.assert_called_once_with(5)
        mock_bridge.add_rehearsal_mark.assert_called_once_with("B")
        assert result["result"] == "ok"

    @pytest.mark.anyio()
    async def test_set_tempo_with_text_delegates_correctly(self) -> None:
        # Arrange
        from mcp_score.tools.manipulation import set_live_tempo

        mock_bridge = AsyncMock()
        mock_bridge.is_connected = True
        mock_bridge.set_tempo = AsyncMock(return_value={"result": "ok"})

        with patch("mcp_score.tools.get_active_bridge", return_value=mock_bridge):
            # Act
            result = json.loads(await set_live_tempo(1, 66, "Slow Blues"))

        # Assert
        mock_bridge.set_tempo.assert_called_once_with(66, "Slow Blues")
        assert result["result"] == "ok"

    @pytest.mark.anyio()
    async def test_transpose_selects_range_and_transposes(
        self,
    ) -> None:
        # Arrange
        from mcp_score.tools.manipulation import transpose_passage

        mock_bridge = AsyncMock(spec=MuseScoreBridge)
        mock_bridge.is_connected = True
        mock_bridge.go_to_measure = AsyncMock(return_value={"result": "ok"})
        mock_bridge.go_to_staff = AsyncMock(return_value={"result": "ok"})
        mock_bridge.send_command = AsyncMock(return_value={"result": "ok"})

        with patch("mcp_score.tools.get_active_bridge", return_value=mock_bridge):
            # Act
            await transpose_passage(1, 8, 0, 5)

        # Assert — two send_command calls: selectCustomRange + transpose
        assert mock_bridge.send_command.call_count == 2
        select_call = mock_bridge.send_command.call_args_list[0]
        assert select_call.args[0] == "selectCustomRange"
        assert select_call.args[1]["startStaff"] == 0
        assert select_call.args[1]["endStaff"] == 0
        transpose_call = mock_bridge.send_command.call_args_list[1]
        assert transpose_call.args[0] == "transpose"
        assert transpose_call.args[1]["semitones"] == 5

    @pytest.mark.anyio()
    async def test_set_barline_navigates_and_delegates(self) -> None:
        # Arrange
        from mcp_score.tools.manipulation import set_live_barline

        mock_bridge = AsyncMock()
        mock_bridge.is_connected = True
        mock_bridge.set_barline = AsyncMock(return_value={"result": {"type": "double"}})

        with patch("mcp_score.tools.get_active_bridge", return_value=mock_bridge):
            # Act
            result = json.loads(await set_live_barline(3, "double"))

        # Assert
        mock_bridge.go_to_measure.assert_called_once_with(3)
        mock_bridge.set_barline.assert_called_once_with("double")
        assert result["result"]["type"] == "double"

    @pytest.mark.anyio()
    async def test_set_key_signature_navigates_and_delegates(self) -> None:
        # Arrange
        from mcp_score.tools.manipulation import set_live_key_signature

        mock_bridge = AsyncMock()
        mock_bridge.is_connected = True
        mock_bridge.set_key_signature = AsyncMock(
            return_value={"result": {"fifths": -3}}
        )

        with patch("mcp_score.tools.get_active_bridge", return_value=mock_bridge):
            # Act
            result = json.loads(await set_live_key_signature(1, -3))

        # Assert
        mock_bridge.go_to_measure.assert_called_once_with(1)
        mock_bridge.set_key_signature.assert_called_once_with(-3)
        assert result["result"]["fifths"] == -3

    @pytest.mark.anyio()
    async def test_add_chord_symbol_navigates_and_delegates(self) -> None:
        # Arrange
        from mcp_score.tools.manipulation import add_live_chord_symbol

        mock_bridge = AsyncMock()
        mock_bridge.is_connected = True
        mock_bridge.add_chord_symbol = AsyncMock(
            return_value={"result": {"text": "Dm7"}}
        )

        with patch("mcp_score.tools.get_active_bridge", return_value=mock_bridge):
            # Act
            result = json.loads(await add_live_chord_symbol(2, "Dm7"))

        # Assert
        mock_bridge.go_to_measure.assert_called_once_with(2)
        mock_bridge.add_chord_symbol.assert_called_once_with("Dm7")
        assert result["result"]["text"] == "Dm7"

    @pytest.mark.anyio()
    async def test_undo_delegates_to_bridge_undo(self) -> None:
        # Arrange
        from mcp_score.tools.manipulation import undo_last_action

        mock_bridge = AsyncMock()
        mock_bridge.is_connected = True
        mock_bridge.undo = AsyncMock(return_value={"result": "ok"})

        with patch("mcp_score.tools.get_active_bridge", return_value=mock_bridge):
            # Act
            result = json.loads(await undo_last_action())

        # Assert
        mock_bridge.undo.assert_called_once()
        assert result["result"] == "ok"


class TestEdgeCases:
    """Edge cases that exercise boundary conditions in tool logic."""

    @pytest.mark.anyio()
    async def test_read_passage_single_measure(self) -> None:
        """start == end is a valid single-measure read."""
        from mcp_score.tools.analysis import read_passage

        mock_bridge = AsyncMock()
        mock_bridge.is_connected = True
        mock_bridge.get_cursor_info = AsyncMock(return_value={"beat": 1})

        with patch("mcp_score.tools.get_active_bridge", return_value=mock_bridge):
            result = json.loads(await read_passage(5, 5))

        assert result["success"] is True
        assert len(result["elements"]) == 1

    @pytest.mark.anyio()
    async def test_transpose_single_measure(self) -> None:
        """start == end is a valid single-measure transpose."""
        from mcp_score.tools.manipulation import transpose_passage

        mock_bridge = AsyncMock(spec=MuseScoreBridge)
        mock_bridge.is_connected = True
        mock_bridge.go_to_measure = AsyncMock(return_value={"result": "ok"})
        mock_bridge.go_to_staff = AsyncMock(return_value={"result": "ok"})
        mock_bridge.send_command = AsyncMock(return_value={"result": "ok"})

        with patch("mcp_score.tools.get_active_bridge", return_value=mock_bridge):
            result = json.loads(await transpose_passage(5, 5, 0, 2))

        assert "error" not in result
        assert mock_bridge.send_command.call_count == 2


class TestBridgeTypeGuards:
    """Tools that use MuseScore-specific commands must reject other bridges."""

    @pytest.mark.anyio()
    async def test_transpose_with_non_musescore_bridge_returns_error(self) -> None:
        # Arrange
        from mcp_score.tools.manipulation import transpose_passage

        mock_bridge = AsyncMock()
        mock_bridge.is_connected = True
        mock_bridge.application_name = "Dorico"

        with patch("mcp_score.tools.get_active_bridge", return_value=mock_bridge):
            # Act
            result = json.loads(await transpose_passage(1, 4, 0, 2))

        # Assert
        assert "only supported with MuseScore" in result["error"]

    @pytest.mark.anyio()
    async def test_get_measure_content_with_non_musescore_returns_warning(
        self,
    ) -> None:
        # Arrange
        from mcp_score.tools.analysis import get_measure_content

        mock_bridge = AsyncMock()
        mock_bridge.is_connected = True
        mock_bridge.go_to_measure = AsyncMock(return_value={"result": "ok"})
        mock_bridge.go_to_staff = AsyncMock(return_value={"result": "ok"})

        with patch("mcp_score.tools.get_active_bridge", return_value=mock_bridge):
            # Act
            result = json.loads(await get_measure_content(1, staff=0))

        # Assert
        assert "warning" in result
        mock_bridge.send_command.assert_not_called()


class TestNavigationErrorHandling:
    """Tools must propagate navigation errors instead of proceeding."""

    @pytest.mark.anyio()
    async def test_read_passage_with_navigation_error_returns_error(self) -> None:
        # Arrange
        from mcp_score.tools.analysis import read_passage

        mock_bridge = AsyncMock()
        mock_bridge.is_connected = True
        mock_bridge.go_to_measure = AsyncMock(
            return_value={"error": "Measure 99 out of range"}
        )

        with patch("mcp_score.tools.get_active_bridge", return_value=mock_bridge):
            # Act
            result = json.loads(await read_passage(99, 100))

        # Assert
        assert "error" in result
        mock_bridge.get_cursor_info.assert_not_called()

    @pytest.mark.anyio()
    async def test_transpose_with_navigation_error_returns_error(self) -> None:
        # Arrange
        from mcp_score.tools.manipulation import transpose_passage

        mock_bridge = AsyncMock(spec=MuseScoreBridge)
        mock_bridge.is_connected = True
        mock_bridge.go_to_measure = AsyncMock(
            return_value={"error": "Measure 99 out of range"}
        )

        with patch("mcp_score.tools.get_active_bridge", return_value=mock_bridge):
            # Act
            result = json.loads(await transpose_passage(99, 100, 0, 2))

        # Assert
        assert "error" in result
        mock_bridge.send_command.assert_not_called()
