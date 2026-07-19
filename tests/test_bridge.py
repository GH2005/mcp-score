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
