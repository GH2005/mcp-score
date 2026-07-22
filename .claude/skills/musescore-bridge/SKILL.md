---
name: musescore-bridge
description: >
  Correct usage patterns for the mcp-score MCP server's live MuseScore tools
  and the mcp-score-bridge MuseScore plugin's WebSocket wire protocol. Use
  BEFORE calling any of: connect_to_musescore, disconnect_from_musescore,
  connect_to_dorico, disconnect_from_dorico, connect_to_sibelius,
  disconnect_from_sibelius, ping_score_app, get_live_score_info,
  read_passage, get_measure_content, get_selection_properties,
  export_live_score, add_live_rehearsal_mark, add_live_notes,
  set_live_time_signature, append_live_measures, process_live_sequence,
  transpose_passage, add_live_chord_symbol, set_live_barline,
  set_live_key_signature, set_live_tempo, or undo_last_action -- or before
  sending any raw JSON command to the plugin's WebSocket bridge
  (ws://localhost:8765, e.g. ping, getScore, goToMeasure, goToStaff,
  addNote, addRehearsalMark, setTimeSignature, appendMeasures, transpose,
  undo, processSequence, exportScore, apiProbe) -- or before editing
  src/mcp_score/musescore/plugin.qml. Also trigger on phrases like "connect
  to MuseScore", "read/write the live score", "what's in the open score",
  "add notes to the score", "transpose the passage", "undo in MuseScore",
  "MuseScore plugin", "mcp-score-bridge", "live score manipulation".
  Several of these commands crash or silently corrupt MuseScore Studio
  4.7.4 if called the wrong way -- read this before guessing at
  parameters.
allowed-tools: [Read]
metadata:
  version: "1.0"
---

# MuseScore bridge — correct usage

**Before calling any mcp-score MCP tool or sending any command to the
MuseScore plugin's WebSocket bridge, read `docs/agent-playbook.md` in
full — via its absolute path,
`C:\Users\GH200\mcp-score-workspace\mcp-score\docs\agent-playbook.md`.**
(A relative link from this file does NOT reliably resolve: this skill
may be loaded through the `~/.claude/skills/` junction, and Windows
collapses `..` against the junction path before following it to the
real directory, landing outside the repo. The absolute path always
works regardless of which copy loaded.) It is the single source of
truth, verified against a live MuseScore Studio 4.7.4 by the committed
test suite (`tests/live/`) — do not guess at parameters, defaults, or
which commands are safe to call.

## If you only remember five things

1. **Never use `format: "mscz"`** in `export_live_score` / `exportScore`.
   It writes a 0-byte file, never replies, and blocks MuseScore with a
   modal dialog the user must dismiss by hand. Use `"musicxml"`.
2. **`transpose_passage` / wire `transpose`** takes ranged parameters
   (`start_measure`/`end_measure`/`staff`/`semitones`, or
   `startMeasure`/`endMeasure`/`startStaff`/`endStaff` on the wire) in a
   single call. Do NOT select-then-transpose — selection-based
   transposition cannot work in MuseScore 4 (`selectRange` never produces
   an active selection there).
3. **`set_live_barline` and `add_live_chord_symbol` crash MuseScore
   outright; `set_live_key_signature` and `set_live_tempo` silently
   corrupt the score.** All four MCP tools refuse to run and explain why —
   do not try to force them past the guard. The wire-level
   `__experimental: true` flag exists but WILL crash or corrupt MuseScore;
   only use it against a disposable, already-saved test score with the
   user's explicit go-ahead.
4. **`undo_last_action` / wire `undo` reports `"ok"` but does nothing** in
   MuseScore Studio 4.7.4. Never rely on it to fix a mistake — make an
   explicit corrective edit instead, and confirm the result with a read.
5. **Never trust a reply as proof an edit landed.** Verify with
   `read_passage` / `get_measure_content` / `export_live_score`
   (ground-truth, export-based reads) after every mutating call.

## Full reference

`docs/agent-playbook.md` has the verified call signature, defaults, and
support status for every one of the 23 MCP tools and every plugin wire
command, plus the restart matrix (MuseScore vs. Claude Code) and how to
re-run the live suite (`pytest -m live tests/live`) if anything here
seems wrong or MuseScore's behavior has changed since it was last
verified.
