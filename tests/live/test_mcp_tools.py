"""MCP tool functions exercised end-to-end against the live bridge.

The tools are called directly as async functions (FastMCP's decorator
returns the original function), so this layer covers everything except
MCP stdio serialization.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

import pytest

from mcp_score.tools.analysis import (
    get_measure_content,
    get_selection_properties,
    read_passage,
)
from mcp_score.tools.connection import (
    connect_to_dorico,
    connect_to_musescore,
    connect_to_sibelius,
    disconnect_from_dorico,
    disconnect_from_musescore,
    get_live_score_info,
    ping_score_app,
)
from mcp_score.tools.manipulation import (
    add_live_chord_symbol,
    add_live_rehearsal_mark,
    set_live_barline,
    set_live_key_signature,
    set_live_tempo,
    transpose_passage,
    undo_last_action,
)
from tests.live import mxl

if TYPE_CHECKING:
    from mcp_score.bridge.musescore import MuseScoreBridge
    from tests.live.conftest import ScratchFn, SnapshotFn

pytestmark = pytest.mark.anyio

QUARTER = {"numerator": 1, "denominator": 4}

ToolCall = tuple[Callable[..., Awaitable[str]], tuple[Any, ...]]

GUARDED_TOOLS: list[ToolCall] = [
    (read_passage, (1, 2)),
    (get_measure_content, (1,)),
    (get_selection_properties, ()),
    (get_live_score_info, ()),
    (ping_score_app, ()),
    (add_live_rehearsal_mark, (1, "X")),
    (add_live_chord_symbol, (1, "C")),
    (set_live_barline, (1, "double")),
    (set_live_key_signature, (1, 0)),
    (set_live_tempo, (1, 100)),
    (transpose_passage, (1, 1, 0, 1)),
    (undo_last_action, ()),
]


@pytest.mark.parametrize(
    ("tool", "args"),
    GUARDED_TOOLS,
    ids=[tool.__name__ for tool, _ in GUARDED_TOOLS],
)
async def test_guarded_tools_report_not_connected(
    no_active_bridge: None,
    tool: Callable[..., Awaitable[str]],
    args: tuple[Any, ...],
) -> None:
    reply = json.loads(await tool(*args))
    assert "error" in reply
    assert "Not connected" in reply["error"]


async def test_ping_score_app(bridge: MuseScoreBridge) -> None:
    reply = json.loads(await ping_score_app())
    assert reply.get("success") is True
    assert "MuseScore" in reply["message"]


async def test_get_live_score_info_matches_export(
    bridge: MuseScoreBridge, snapshot: SnapshotFn
) -> None:
    reply = json.loads(await get_live_score_info())
    snap = await snapshot("toolinfo")
    assert reply["result"]["measureCount"] == snap["measure_count"]


async def test_get_selection_properties_returns_cursor_info(
    bridge: MuseScoreBridge,
) -> None:
    reply = json.loads(await get_selection_properties())
    assert set(reply["result"]) >= {"measure", "staff", "beat", "tick"}


@pytest.mark.xfail(
    reason="read_passage walks the cursor and reports only the first "
    "element of each measure (chords/voices/later beats are invisible). "
    "Rewrite onto exportScore + music21 planned (PR3).",
    strict=True,
)
async def test_read_passage_reports_full_measure_content(
    bridge: MuseScoreBridge, scratch: ScratchFn
) -> None:
    """read_passage must report every note in each measure, not just the
    element under the cursor."""
    first, second = await scratch(2)
    seq_reply = await bridge.process_sequence(
        [
            {"action": "goToStaff", "params": {"staff": 0}},
            {"action": "goToMeasure", "params": {"measure": first}},
            {"action": "addNote", "params": {"pitch": 60, "duration": QUARTER}},
            {"action": "addNote", "params": {"pitch": 64, "duration": QUARTER}},
            {"action": "goToMeasure", "params": {"measure": second}},
            {"action": "addNote", "params": {"pitch": 67, "duration": QUARTER}},
        ]
    )
    assert "result" in seq_reply, f"setup failed: {seq_reply}"

    reply = json.loads(await read_passage(first, second, staff=0))
    assert reply.get("success") is True
    assert len(reply["elements"]) == 2

    first_content = json.dumps(reply["elements"][0])
    assert "60" in first_content and "64" in first_content, (
        f"measure {first} content misses notes (C4+E4 were written): "
        f"{reply['elements'][0]}"
    )


@pytest.mark.xfail(
    reason="get_measure_content returns only {measure, staff} -- the "
    "selectCurrentMeasure reply carries no musical content at all. "
    "Rewrite onto exportScore + music21 planned (PR3).",
    strict=True,
)
async def test_get_measure_content_reports_notes(
    bridge: MuseScoreBridge, scratch: ScratchFn
) -> None:
    start, _ = await scratch(1)
    assert "result" in await bridge.go_to_staff(0)
    assert "result" in await bridge.go_to_measure(start)
    assert "result" in await bridge.add_note(62, QUARTER)

    reply = json.loads(await get_measure_content(start, staff=0))
    content = json.dumps(reply)
    assert "62" in content, (
        f"measure content does not include the D4 that was written: {reply}"
    )


async def test_add_live_rehearsal_mark_tool(
    bridge: MuseScoreBridge, scratch: ScratchFn, snapshot: SnapshotFn
) -> None:
    start, _ = await scratch(1)
    before = await snapshot("tool-rehearsal-before")
    reply = json.loads(await add_live_rehearsal_mark(start, "TOOL-T1"))
    assert "error" not in reply, f"tool failed: {reply}"

    after = await snapshot("tool-rehearsal-after")
    changes = mxl.diff_snapshots(before, after)
    assert f"s0m{start}" in changes
    assert changes[f"s0m{start}"]["after"].get("rehearsal") == ["TOOL-T1"]


async def test_manipulation_tools_validate_measure(
    bridge: MuseScoreBridge,
) -> None:
    for coro in (
        add_live_rehearsal_mark(0, "X"),
        add_live_chord_symbol(0, "C"),
        set_live_barline(0, "double"),
        set_live_key_signature(0, 0),
        set_live_tempo(0, 100),
    ):
        reply = json.loads(await coro)
        assert "error" in reply
        assert "must be >= 1" in reply["error"]


@pytest.mark.xfail(
    reason="curScore.transpose() does not exist in MuseScore 4.7.4, so "
    "transpose_passage always fails. Reimplementation planned (PR5).",
    strict=True,
)
async def test_transpose_passage_tool_end_to_end(
    bridge: MuseScoreBridge, scratch: ScratchFn, snapshot: SnapshotFn
) -> None:
    start, end = await scratch(2)
    seq_reply = await bridge.process_sequence(
        [
            {"action": "goToStaff", "params": {"staff": 0}},
            {"action": "goToMeasure", "params": {"measure": start}},
            {"action": "addNote", "params": {"pitch": 60, "duration": QUARTER}},
            {"action": "goToMeasure", "params": {"measure": end}},
            {"action": "addNote", "params": {"pitch": 62, "duration": QUARTER}},
        ]
    )
    assert "result" in seq_reply, f"setup failed: {seq_reply}"
    before = await snapshot("tool-transpose-before")

    reply = json.loads(await transpose_passage(start, end, 0, 2))
    assert "error" not in reply, f"transpose_passage failed: {reply}"

    after = await snapshot("tool-transpose-after")
    changes = mxl.diff_snapshots(before, after)
    assert set(changes) == {f"s0m{start}", f"s0m{end}"}, (
        f"delta not confined to staff 0, measures {start}-{end}: {set(changes)}"
    )
    for measure, expected in ((start, 62), (end, 64)):
        notes = [
            e
            for e in changes[f"s0m{measure}"]["after"]["events"]
            if e["kind"] != "rest"
        ]
        assert [e["midi"] for e in notes] == [[expected]]


async def test_transpose_passage_invalid_range_returns_error(
    bridge: MuseScoreBridge,
) -> None:
    reply = json.loads(await transpose_passage(5, 2, 0, 1))
    assert "error" in reply


@pytest.mark.xfail(
    reason="cmd('undo') is a silent no-op from the dock-plugin context "
    "in MuseScore 4.7.4; undo_last_action reports ok without undoing. "
    "Fix planned (PR5).",
    strict=True,
)
async def test_undo_last_action_tool(
    bridge: MuseScoreBridge, scratch: ScratchFn, snapshot: SnapshotFn
) -> None:
    start, _ = await scratch(1)
    assert "result" in await bridge.go_to_staff(0)
    assert "result" in await bridge.go_to_measure(start)
    before = await snapshot("tool-undo-before")

    assert "result" in await bridge.add_note(60, QUARTER)
    reply = json.loads(await undo_last_action())
    assert "error" not in reply, f"undo_last_action failed: {reply}"

    after = await snapshot("tool-undo-after")
    assert mxl.diff_snapshots(before, after) == {}


# ── Connection churn (kept last; each test restores the connection) ──


async def test_connect_to_musescore_happy_path(
    bridge: MuseScoreBridge, restore_musescore_connection: None
) -> None:
    reply = json.loads(await connect_to_musescore())
    assert reply.get("success") is True


async def test_connect_to_musescore_wrong_port_returns_error(
    bridge: MuseScoreBridge, restore_musescore_connection: None
) -> None:
    reply = json.loads(await connect_to_musescore(port=19999))
    assert "error" in reply
    assert "Could not connect" in reply["error"]


async def test_disconnect_from_musescore_is_idempotent(
    bridge: MuseScoreBridge, restore_musescore_connection: None
) -> None:
    first = json.loads(await disconnect_from_musescore())
    second = json.loads(await disconnect_from_musescore())
    assert first.get("success") is True
    assert second.get("success") is True


async def test_connect_to_dorico_without_dorico_returns_error(
    bridge: MuseScoreBridge, restore_musescore_connection: None
) -> None:
    reply = json.loads(await connect_to_dorico())
    assert "error" in reply
    assert "Dorico" in reply["error"]
    # A failed Dorico connect must not leave a half-configured active bridge.
    cleanup = json.loads(await disconnect_from_dorico())
    assert cleanup.get("success") is True


async def test_connect_to_sibelius_without_sibelius_returns_error(
    bridge: MuseScoreBridge, restore_musescore_connection: None
) -> None:
    reply = json.loads(await connect_to_sibelius())
    assert "error" in reply
    assert "Sibelius" in reply["error"]
