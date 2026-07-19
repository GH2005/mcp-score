# Agent playbook — verified mcp-score usage patterns

> Reference — every claim here was verified against a live MuseScore
> Studio 4.7.4 (Windows 11) by the committed live test suite
> (`tests/live/`). Verification date: 2026-07-19. Plugin version: 0.2.0.
> When in doubt, re-run the suite; it is the source of truth.

## The stack

```
MCP tool  →  ScoreBridge (Python)  →  ws://localhost:8765  →  plugin.qml  →  curScore
```

- The plugin (`mcp-score-bridge.qml`) must be running inside MuseScore:
  **Plugins → MCP Score Bridge** (a dock plugin; it must be relaunched
  after every MuseScore restart).
- Wire protocol: one JSON object per message,
  `{"command": <name>, "params": {...}}` → `{"result": ...}` or
  `{"error": "..."}`. There are no message ids; correlation is strict
  request→response lock-step, so keep one request in flight per client.
- Multiple clients may connect simultaneously (verified: replies are
  routed per client), but each client must still serialize its own
  requests.

## Ground-truth doctrine (the most important rule)

**Never trust a bridge reply as proof that an edit landed.** MuseScore
4's plugin API fails silently in several places. The accurate read path:

1. Snapshot the live score (captures unsaved edits, works on never-saved
   scores, does not touch the user's file): call the `export_live_score`
   tool, or send `{"command": "exportScore", "params": {"path":
   "C:/abs/path/out.musicxml", "format": "musicxml"}}`.
2. Parse the MusicXML (`mcp_score.musicxml.parse_snapshot`) and/or
   render it with MuseScore's CLI for a visual check
   (`MuseScore4.exe <in> -o <out>.png -r 130 --force`; works while the
   GUI is open; on Windows launch with `Start-Process -Wait` because the
   exe detaches when invoked directly).
3. Verify an edit by diffing snapshots taken before and after
   (`mcp_score.musicxml.diff_snapshots`) — the delta must be exactly the
   intended change.

`read_passage` and `get_measure_content` implement this doctrine
internally, so their output is trustworthy.

## Support matrix (MuseScore Studio 4.7.4)

### Works — verified live

| Surface | Notes |
|---|---|
| `ping_score_app`, `get_live_score_info` | `getScore` reply carries `pluginVersion` (stale-plugin detection), `measureCount`, key/time signature, parts with staff ranges (derived from tracks). |
| `export_live_score(path?, format="musicxml")` | The ground-truth snapshot. Rejects `mscz` (see limitations), relative paths, unknown formats. |
| `read_passage(start, end, staff?)` | Accurate: export + parse. Reports every note, chord, rest, voice, and annotation per measure/staff. |
| `get_measure_content(measure, staff=0)` | Accurate: export + parse. |
| `get_selection_properties` | Cursor info only (measure/staff/beat/tick + element under cursor). |
| `add_live_notes(measure, staff, notes)` | The reliable note-entry path: writes a consecutive run atomically via `processSequence`. Notes replace existing content at those beats and spill into following measures. `{"pitch": 0-127, "numerator": 1, "denominator": 4}` per note. |
| `process_live_sequence(steps)` | Batch of wire actions in one command group. Rejects crash/corruption actions. **Rollback on failure does not work** (undo is broken): earlier steps stay applied. |
| `add_live_rehearsal_mark(measure, text)` | Verified in export. |
| `set_live_time_signature(measure, num, den)` | Verified in export; re-bars from that measure onward; may add a courtesy signature to the previous measure. |
| `append_live_measures(count)` | Verified in export. |
| `transpose_passage(start, end, staff, semitones)` | Reimplemented note-by-note with correct enharmonic spelling (tpc math). Sends the single ranged `transpose` message. |
| Wire navigation: `goToMeasure` (1-indexed), `goToStaff` (0-indexed) | Bounds-checked. Staff persists across commands; always set it explicitly. |
| Wire `addNote` | Consecutive calls accumulate (the plugin tracks the intra-measure tick). `goToMeasure`/`goToStaff` reset the position to the measure start. Pitch validated 0–127. |
| Wire `getCursorInfo` | Beat computed via `measure.timesigActual`; note names derived from tpc+pitch (e.g. `"C4"`, `"Eb3"`). Reports only the element under the cursor — use the export path for full content. |
| Wire `apiProbe` | Runtime introspection of the plugin API (diagnostic). |

### Broken in MuseScore 4.7.4 — guarded, do not attempt to bypass

| Surface | Failure mode | Guard |
|---|---|---|
| `setBarline`, `addChordSymbol`, `addDynamic` | **Crash MuseScore outright** (process death; `newElement` + `cursor.add` is fatal for these element types). | Tools refuse; wire commands require `__experimental: true`; `process_live_sequence` rejects the actions. |
| `setKeySignature`, `setTempo` | **Silently insert corrupt elements**: every inserted key signature exports as `fifths=-8` regardless of the value written; tempo marks export with no text and no number. The clone made by `cursor.add` loses the assigned values; re-assigning after insertion does not help. (`setTimeSignature` and rehearsal marks use the same pattern and work — the MS4 API port is that inconsistent.) | Tools refuse; `process_live_sequence` rejects the actions. |
| `undo` (and `processSequence` rollback) | `cmd("undo")` is a **silent no-op** from the dock-plugin context: the reply says ok, the edit stays. | None (reply is honest-looking but useless). Never rely on undo; verify with exports and fix mistakes with explicit edits. |
| Selection-based transposition | `selection.selectRange` does not produce an active selection (elements stays empty), with or without a command group. | Use the ranged `transpose` parameters instead. |
| `newScore` | Creates the score in a window this bridge cannot control; `curScore` never switches to it. | Not exposed as a tool. |
| `exportScore` with `format: "mscz"` | writeScore writes a 0-byte file, never replies, and raises a **blocking modal dialog** the user must dismiss by hand. | Rejected at both the tool and the plugin level. |

### Not available on this machine

Dorico (port 4560) and Sibelius (port 1898) are not installed; only
their connection-failure paths are verified.

## Running the live suite

```bash
uv run --project <repo> pytest -m live tests/live -q
```

- Requires MuseScore running with the plugin serving `ws://localhost:8765`
  (the suite skips itself otherwise).
- **The suite mutates the open score** (appends scratch measures and
  writes test content). A guard refuses to run unless the score title
  contains "untitled", "scratch", or "mcp" (override:
  `MCP_SCORE_LIVE_ANY_SCORE=1`).
- Tests allocate fresh scratch measures at the score tail at call time
  and assert delta-scoped MusicXML diffs, so a dirty score never causes
  false failures. Undo is never used for cleanup.
- Every skip/xfail reason string documents a verified MuseScore 4.7.4
  defect. A strict xfail that starts XPASSing means MuseScore fixed
  something — remove the marker and enjoy.
- Plain `pytest` (CI, the pre-push hook) excludes the live suite via
  `addopts`; no MuseScore needed.

## Restart matrix

| You changed | Redeploy | Restart needed |
|---|---|---|
| `plugin.qml` | `mcp-score install-plugin` | MuseScore restart + relaunch the plugin dock. Confirm with `getScore` → `pluginVersion`. |
| Python source, exercised via the live suite | nothing (`uv run --project` uses the source tree) | none |
| Python source, exercised via an MCP client | reinstall/refresh however the client launches the server | restart the MCP client (e.g. Claude Code) |

## Gotchas learned the hard way

- Key signatures apply from their measure forward; expect the export
  diff to show only the measure that got the signature.
- Time-signature changes re-bar everything after them and may put a
  courtesy signature at the end of the previous measure.
- `goToStaff` persists across commands — a forgotten staff switch makes
  later edits land on the wrong staff.
- Rehearsal marks and tempo/system text live on staff 0 in exports.
- The bridge auto-connects and retries once on connection loss
  (`RECV_TIMEOUT` 30 s). "Cannot connect" errors right after a MuseScore
  restart usually mean the plugin dock has not been relaunched.
- If MuseScore crashes, everything unsaved is gone: the wire commands
  that crash it are gated for exactly this reason. Do not pass
  `__experimental: true` outside a deliberate, saved-score experiment.

## Adding a new command end-to-end

1. QML: add the `case` in `handleMessage` + a `handle...` function
   (validate params first; wrap mutations in `startCmd`/`try`/`finally`
   `endCmd`).
2. Bridge: add a convenience method in
   `src/mcp_score/bridge/musescore.py`.
3. Tool: add the `@mcp.tool()` in `src/mcp_score/tools/` (guard with
   `connected_bridge()` / `check_measure` / `_require_musescore`).
4. Tests: mocked (CI) + live (delta-scoped MusicXML diff).
5. Install the plugin, restart MuseScore, run the live suite.
6. Update this playbook's support matrix.
