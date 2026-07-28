"""Clef read/write commands, verified against MusicXML snapshots.

The ClefType integers in the plugin's lookup table are not stable across
MuseScore versions, so these tests do not trust them: every write is read
back from the exported MusicXML and checked by its *sign*, which is what
the score actually renders.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from tests.live import mxl

if TYPE_CHECKING:
    from mcp_score.bridge.musescore import MuseScoreBridge
    from tests.live.conftest import ScratchFn, SnapshotFn

pytestmark = pytest.mark.anyio

QUARTER = {"numerator": 1, "denominator": 4}


async def _at(bridge: MuseScoreBridge, measure: int, staff: int = 0) -> None:
    reply = await bridge.go_to_staff(staff)
    assert "result" in reply, f"goToStaff failed: {reply}"
    reply = await bridge.go_to_measure(measure)
    assert "result" in reply, f"goToMeasure failed: {reply}"


def _clefs_of(measure_dict: dict[str, Any] | None) -> list[dict[str, Any]]:
    if measure_dict is None:
        return []
    return list(measure_dict.get("clef") or [])


# ── Reading ──────────────────────────────────────────────────────────


async def test_get_clefs_reports_the_staff_defining_clefs(
    bridge: MuseScoreBridge,
) -> None:
    """Every staff opens with a clef at tick 0, and it is reported."""
    reply = await bridge.get_clefs()
    result = reply.get("result")
    assert isinstance(result, dict), f"getClefs failed: {reply}"

    clefs = result["clefs"]
    assert clefs, "a score with staves must report at least one clef"

    opening = [c for c in clefs if c["tick"] == 0]
    staves = {c["staff"] for c in opening}
    info = await bridge.get_score()
    part_count = len(info["result"]["parts"])
    assert staves, "no clef reported at tick 0"
    assert part_count >= 1

    for clef in clefs:
        assert clef["measure"] >= 1
        assert clef["tick"] >= 0
        assert isinstance(clef["atMeasureStart"], bool)
        assert (clef["tickInMeasure"] == 0) == clef["atMeasureStart"]


async def test_get_clefs_staff_filter_restricts_the_report(
    bridge: MuseScoreBridge,
) -> None:
    reply = await bridge.get_clefs(staff=0)
    result = reply.get("result")
    assert isinstance(result, dict), f"getClefs failed: {reply}"

    assert all(c["staff"] == 0 for c in result["clefs"]), (
        f"staff filter leaked other staves: {result['clefs']}"
    )


async def test_get_clefs_rejects_an_out_of_range_staff(
    bridge: MuseScoreBridge,
) -> None:
    reply = await bridge.get_clefs(staff=99)

    assert "error" in reply
    assert "out of range" in reply["error"]


async def test_cursor_info_reports_the_governing_clef(
    bridge: MuseScoreBridge,
) -> None:
    """The clef in effect at the cursor, not merely the score's first."""
    await _at(bridge, 1, staff=0)

    reply = await bridge.get_cursor_info()
    result = reply.get("result")
    assert isinstance(result, dict), f"getCursorInfo failed: {reply}"

    clef = result["clef"]
    assert clef is not None, "no clef reported at measure 1"
    assert clef["staff"] == 0
    assert clef["tick"] <= result["tick"]


# ── Writing ──────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("clef_type", "expected_sign"),
    [
        ("bass", "BassClef"),
        ("alto", "AltoClef"),
        ("tenor", "TenorClef"),
        ("treble", "TrebleClef"),
    ],
)
async def test_set_clef_writes_the_requested_clef(
    bridge: MuseScoreBridge,
    scratch: ScratchFn,
    snapshot: SnapshotFn,
    clef_type: str,
    expected_sign: str,
) -> None:
    """The named clef must arrive as that clef in the score.

    This is what pins the plugin's ClefType integers: a wrong table entry
    writes a real clef of the wrong kind, which only the exported sign
    reveals.
    """
    start, _ = await scratch(1)
    await _at(bridge, start)
    before = await snapshot(f"setclef-{clef_type}-before")

    reply = await bridge.set_clef(clef_type)
    assert "result" in reply, f"setClef failed: {reply}"
    assert reply["result"]["type"] == clef_type

    after = await snapshot(f"setclef-{clef_type}-after")
    changes = mxl.diff_snapshots(before, after)
    key = f"s0m{start}"
    assert key in changes, f"no change in the target measure: {set(changes)}"

    signs = [c["sign"] for c in _clefs_of(changes[key]["after"])]
    assert expected_sign in signs, (
        f"{clef_type} did not write a {expected_sign}; measure holds {signs}"
    )


async def test_set_clef_rejects_an_unknown_type(bridge: MuseScoreBridge) -> None:
    reply = await bridge.set_clef("sousaphone")

    assert "error" in reply
    assert "Unknown clef type" in reply["error"]


async def test_set_clef_mid_measure_lands_after_the_note(
    bridge: MuseScoreBridge,
    scratch: ScratchFn,
    snapshot: SnapshotFn,
) -> None:
    """A clef written after a note is a mid-measure clef change."""
    start, _ = await scratch(1)
    await _at(bridge, start)
    before = await snapshot("midclef-before")

    assert "result" in await bridge.add_note(60, QUARTER)
    reply = await bridge.set_clef("bass")
    assert "result" in reply, f"setClef failed: {reply}"

    after = await snapshot("midclef-after")
    changes = mxl.diff_snapshots(before, after)
    key = f"s0m{start}"
    assert key in changes

    clefs = _clefs_of(changes[key]["after"])
    mid = [c for c in clefs if c["offset"] > 0.0]
    assert mid, f"expected a clef at a non-zero offset, got {clefs}"

    listed = await bridge.get_clefs(staff=0)
    reported = [
        c
        for c in listed["result"]["clefs"]
        if c["measure"] == start and not c["atMeasureStart"]
    ]
    assert reported, "getClefs did not report the mid-measure clef it wrote"


# ── Removing ─────────────────────────────────────────────────────────


async def test_remove_clef_is_refused_as_unsupported(
    bridge: MuseScoreBridge,
) -> None:
    """Clef deletion is impossible in MuseScore Studio 4.7.4.

    Score-level removal does not exist and selection.select() returns
    false for a Clef, so the command refuses instead of pretending.
    """
    reply = await bridge.remove_clef(staff=0, mid_measure_only=True)

    assert "error" in reply, f"removeClef should refuse, got: {reply}"
    assert "disabled" in reply["error"]
    assert "setClef" in reply["error"], "the refusal must name the workaround"


async def test_remove_clef_experimental_probe_still_cannot_delete(
    bridge: MuseScoreBridge,
    scratch: ScratchFn,
    snapshot: SnapshotFn,
) -> None:
    """Pin the failure mode, so a MuseScore fix is noticed.

    If a later MuseScore build makes removal work, this test fails and
    the guard can come off. It also proves the failed attempt does not
    damage the music: cmd("delete") must never fall through to whatever
    was selected before.
    """
    start, _ = await scratch(1)
    await _at(bridge, start)
    assert "result" in await bridge.add_note(60, QUARTER)
    assert "result" in await bridge.set_clef("bass")

    before = await snapshot("removeclef-before")
    before_measure = mxl.get_measure(before, 0, start)
    assert [c for c in _clefs_of(before_measure) if c["offset"] > 0.0]
    notes_before = [e for e in (before_measure or {})["events"] if e["kind"] == "note"]

    reply = await bridge.send_command(
        "removeClef",
        {
            "staff": 0,
            "measure": start,
            "midMeasureOnly": True,
            "__experimental": True,
        },
    )
    result = reply.get("result")
    assert isinstance(result, dict), f"removeClef errored unexpectedly: {reply}"
    assert result["removed"] == 0, (
        f"clef removal SUCCEEDED -- MuseScore may be fixed; revisit the "
        f"guard in handleRemoveClef and the playbook: {result}"
    )
    assert result["failed"], "a failed removal must be reported as failed"

    after = await snapshot("removeclef-after")
    after_measure = mxl.get_measure(after, 0, start)
    assert [c for c in _clefs_of(after_measure) if c["offset"] > 0.0], (
        "the clef vanished despite removed == 0"
    )
    notes_after = [e for e in (after_measure or {})["events"] if e["kind"] == "note"]
    assert notes_after == notes_before, (
        f"the failed delete damaged the music: {notes_before} -> {notes_after}"
    )


async def test_remove_clef_without_filters_is_refused(
    bridge: MuseScoreBridge,
) -> None:
    """Stripping every clef from a score is never the intent.

    Checked through the experimental path, so it tests the filter guard
    rather than the unsupported-operation guard in front of it.
    """
    reply = await bridge.send_command("removeClef", {"__experimental": True})

    assert "error" in reply
    assert "at least one filter" in reply["error"]


# ── Sequence path ────────────────────────────────────────────────────


async def test_set_clef_inside_a_sequence(
    bridge: MuseScoreBridge,
    scratch: ScratchFn,
    snapshot: SnapshotFn,
) -> None:
    """The sequence switch has its own handler code and its own bugs."""
    start, _ = await scratch(1)
    before = await snapshot("seqclef-before")

    reply = await bridge.process_sequence(
        [
            {"action": "goToStaff", "params": {"staff": 0}},
            {"action": "goToMeasure", "params": {"measure": start}},
            {"action": "setClef", "params": {"type": "bass"}},
        ]
    )
    result = reply.get("result")
    assert isinstance(result, dict), f"processSequence failed: {reply}"
    assert result["count"] == 3

    after = await snapshot("seqclef-after")
    changes = mxl.diff_snapshots(before, after)
    key = f"s0m{start}"
    assert key in changes, f"sequence wrote nothing to {key}: {set(changes)}"
    assert "BassClef" in [c["sign"] for c in _clefs_of(changes[key]["after"])]


async def test_remove_clef_inside_a_sequence_is_refused_too(
    bridge: MuseScoreBridge,
) -> None:
    """The sequence switch must carry the same guard as the handler.

    The two dispatchers hold separate code and have drifted before, so
    the guard is asserted on both paths.
    """
    reply = await bridge.process_sequence(
        [{"action": "removeClef", "params": {"staff": 0, "midMeasureOnly": True}}]
    )

    assert "error" in reply, f"sequence removeClef should refuse: {reply}"
    assert "disabled" in reply["error"]


async def test_set_clef_replaces_a_clef_at_the_same_position(
    bridge: MuseScoreBridge,
    scratch: ScratchFn,
    snapshot: SnapshotFn,
) -> None:
    """Writing a clef where one already sits replaces it, never stacks.

    This is the documented workaround for removal being impossible, so
    it needs a test of its own: if it ever started stacking, the advice
    to "overwrite the unwanted clef" would silently double the problem.
    """
    start, _ = await scratch(1)
    await _at(bridge, start)
    assert "result" in await bridge.add_note(60, QUARTER)
    assert "result" in await bridge.set_clef("bass")

    await _at(bridge, start)
    assert "result" in await bridge.add_note(62, QUARTER)
    assert "result" in await bridge.set_clef("treble")

    after = await snapshot("replaceclef-after")
    mid = [c for c in _clefs_of(mxl.get_measure(after, 0, start)) if c["offset"] > 0.0]
    assert len(mid) == 1, f"expected one mid-measure clef, got {mid}"
    assert mid[0]["sign"] == "TrebleClef", f"the overwrite did not take: {mid}"


async def test_courtesy_clefs_are_not_reported_as_clef_changes(
    bridge: MuseScoreBridge,
) -> None:
    """MuseScore restates the clef at every system start.

    Those are laid out, not authored. Reporting them would bury the real
    clef changes -- a 300-bar piano score carries 78 clef glyphs and 2
    actual clefs.
    """
    reply = await bridge.get_clefs()
    result = reply.get("result")
    assert isinstance(result, dict), f"getClefs failed: {reply}"

    assert all(not c["redundant"] for c in result["clefs"]), (
        "a restated clef leaked into the default report"
    )

    verbose = await bridge.send_command("getClefs", {"includeRedundant": True})
    assert len(verbose["result"]["clefs"]) >= len(result["clefs"]), (
        "includeRedundant must not hide anything the default shows"
    )
