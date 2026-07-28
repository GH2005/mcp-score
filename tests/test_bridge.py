"""Tests for the MuseScore WebSocket bridge client."""

from unittest.mock import AsyncMock, patch

import pytest
import websockets.exceptions

from mcp_score.bridge.musescore import MuseScoreBridge


class TestMuseScoreBridgeConnection:
    def test_new_bridge_is_not_connected(self) -> None:
        # Arrange
        bridge = MuseScoreBridge()

        # Act / Assert
        assert bridge.is_connected is False

    @pytest.mark.anyio()
    async def test_connect_without_server_returns_false(self) -> None:
        # Arrange
        bridge = MuseScoreBridge(host="localhost", port=19999)

        # Act
        connected = await bridge.connect()

        # Assert
        assert connected is False
        assert bridge.is_connected is False

    @pytest.mark.anyio()
    async def test_send_command_without_server_returns_error(self) -> None:
        # Arrange
        bridge = MuseScoreBridge(host="localhost", port=19999)

        # Act
        result = await bridge.send_command("ping")

        # Assert
        assert "error" in result
        assert "Cannot connect" in result["error"]

    @pytest.mark.anyio()
    async def test_ping_without_connection_returns_false(self) -> None:
        # Arrange
        bridge = MuseScoreBridge(host="localhost", port=19999)

        # Act
        alive = await bridge.ping()

        # Assert
        assert alive is False


class TestMuseScoreBridgeReconnect:
    @pytest.mark.anyio()
    async def test_reconnect_failure_returns_error(self) -> None:
        """When first send fails and reconnect also fails, return error."""
        # Arrange
        bridge = MuseScoreBridge()
        mock_connection = AsyncMock()
        bridge._connection = mock_connection

        mock_connection.send = AsyncMock()
        mock_connection.recv = AsyncMock(
            side_effect=websockets.exceptions.ConnectionClosed(None, None)
        )

        # Act — force the reconnect attempt to fail regardless of whether a
        # real MuseScore instance happens to be listening on localhost:8765
        with patch(
            "mcp_score.bridge.musescore.websockets.connect",
            side_effect=OSError("connection refused"),
        ):
            result = await bridge.send_command("ping")

        # Assert
        assert "error" in result
        assert bridge._connection is None

    @pytest.mark.anyio()
    async def test_non_text_response_returns_error(self) -> None:
        """Binary WebSocket response should produce an error."""
        # Arrange
        bridge = MuseScoreBridge()
        mock_connection = AsyncMock()
        bridge._connection = mock_connection

        mock_connection.send = AsyncMock()
        mock_connection.recv = AsyncMock(return_value=b"binary data")

        # Act
        result = await bridge._send_raw('{"command": "ping"}')

        # Assert
        assert "error" in result
        assert "non-text" in result["error"]


class TestMuseScoreBridgeClefCommands:
    """Clef convenience methods map to the right wire command and params."""

    @pytest.fixture()
    def anyio_backend(self) -> str:
        return "asyncio"

    @staticmethod
    def _bridge_with_capture() -> tuple[MuseScoreBridge, AsyncMock]:
        bridge = MuseScoreBridge()
        sender = AsyncMock(return_value={"result": {}})
        bridge.send_command = sender  # type: ignore[method-assign]
        return bridge, sender

    @pytest.mark.anyio()
    async def test_get_clefs_without_staff_sends_no_filter(self) -> None:
        bridge, sender = self._bridge_with_capture()

        await bridge.get_clefs()

        sender.assert_awaited_once_with("getClefs", {})

    @pytest.mark.anyio()
    async def test_get_clefs_with_staff_filters(self) -> None:
        bridge, sender = self._bridge_with_capture()

        await bridge.get_clefs(staff=1)

        sender.assert_awaited_once_with("getClefs", {"staff": 1})

    @pytest.mark.anyio()
    async def test_set_clef_sends_named_type(self) -> None:
        bridge, sender = self._bridge_with_capture()

        await bridge.set_clef("bass")

        sender.assert_awaited_once_with("setClef", {"type": "bass"})

    @pytest.mark.anyio()
    async def test_set_clef_subtype_takes_precedence_over_name(self) -> None:
        """An explicit ClefType integer is the escape hatch for variants
        the named table does not cover, so it must win."""
        bridge, sender = self._bridge_with_capture()

        await bridge.set_clef("bass", subtype=7)

        sender.assert_awaited_once_with("setClef", {"subtype": 7})

    @pytest.mark.anyio()
    async def test_remove_clef_omits_unset_filters(self) -> None:
        """Only the filters actually given are sent -- a None must not
        arrive as a filter the plugin would try to match."""
        bridge, sender = self._bridge_with_capture()

        await bridge.remove_clef(staff=1, mid_measure_only=True)

        sender.assert_awaited_once_with(
            "removeClef", {"staff": 1, "midMeasureOnly": True}
        )

    @pytest.mark.anyio()
    async def test_remove_clef_maps_measure_range_to_camel_case(self) -> None:
        bridge, sender = self._bridge_with_capture()

        await bridge.remove_clef(staff=0, start_measure=2, end_measure=6)

        sender.assert_awaited_once_with(
            "removeClef", {"staff": 0, "startMeasure": 2, "endMeasure": 6}
        )

    @pytest.mark.anyio()
    async def test_remove_clef_with_no_filters_sends_empty_params(self) -> None:
        """The plugin owns the refusal, so the bridge must not silently
        invent a filter that would narrow an unfiltered request."""
        bridge, sender = self._bridge_with_capture()

        await bridge.remove_clef()

        sender.assert_awaited_once_with("removeClef", {})
