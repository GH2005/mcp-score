# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/).

## [Unreleased]

### Added

- Score generation via Claude Code skill (music21 -> MusicXML)
- MCP server with 25 tools for live score manipulation (MuseScore, Dorico, Sibelius)
- Multi-bridge architecture: MuseScore QML plugin, Dorico Remote Control, Sibelius Connect
- MuseScore 4 QML plugin with WebSocket bridge (23 commands, native api.websocketserver transport)
- CLI install commands: `mcp-score install-skill`, `mcp-score install-plugin`
- Comprehensive test suite (283 tests: 190 mocked + 93 live against a running MuseScore)
- Full documentation (architecture, reference, getting-started)
- GitHub security: CodeQL scanning, branch protection
- Score metadata: subtitle (movementName), arranger (Contributor), copyright support
- Prompt request PR workflow in CONTRIBUTING.md
- Ground-truth read path: `export_live_score` tool + plugin `exportScore` command snapshot the live score to MusicXML, parsed via `src/mcp_score/musicxml.py` (music21)
- Composition tools: `add_live_notes`, `process_live_sequence`, `set_live_time_signature`, `append_live_measures`
- Live test suite (`tests/live/`, `pytest -m live`) verifying every tool and wire command against a running MuseScore by diffing MusicXML snapshots
- Plugin `apiProbe` diagnostic command and `pluginVersion` reporting in `getScore`
- Agent playbook (`docs/agent-playbook.md`): verified MuseScore support matrix and usage patterns
- `mcp_score.theory`: music21-backed spelling, harmonic realization, transposition planning, and passage analysis
- `realize_harmony` tool: roman numeral or chord symbol to correctly spelled pitches (needs no score connection)
- `analyze_passage` tool: advisory report on a live passage -- detected key, roman-numeral harmony, voice-leading observations (parallel/hidden fifths and octaves, voice crossing), per-staff ambitus. Never edits, never blocks
- Plugin 0.3.0 write vocabulary: `addNote` gained `addToChord` and `tpc` (explicit enharmonic spelling), `goToStaff` gained `voice`, plus new `addRest` and `setPitches` commands
- `add_live_notes` accepts spelled note names, chords, rests, and a voice argument

### Changed

- music21 upgraded to v10.5
- Transposition moved out of the plugin: `transpose_passage` now reads a snapshot, computes each new pitch **and its spelling** with music21, and applies verified positional edits via `setPitches`. It transposes every voice, not just voice 0
- The wire `transpose` command and the plugin's hand-rolled tonal-pitch-class tables were removed -- the plugin holds no music theory
- Element descriptions report raw `(pitch, tpc)`; note names are rendered server-side
- Plugin transport ported to MuseScore's native `api.websocketserver` (the QtWebSockets QML module does not exist in MuseScore 4's plugin runtime)
- `read_passage`/`get_measure_content` rewritten onto the export-based ground-truth path for MuseScore (the cursor walk saw at most the first element of a measure)
- Plugin tracks the intra-measure cursor position so consecutive `addNote` commands accumulate instead of overwriting
- Plugin version bumped to 0.3.0

### Fixed

- Voices are now labelled by containment rather than by a context search, which previously reported a neighbouring measure's voice for any measure with no explicit voices -- mislabelling reads and misrouting transposition edits
- Voice numbers map correctly for multi-staff parts (MusicXML numbers voices across a part, 1-4 for the upper staff and 5-8 for the lower; MuseScore numbers 0-3 per staff)
- Consecutive `addNote` steps inside `processSequence` no longer overwrite each other (shared cursor threading)
- `getScore` parts report staff ranges again (derived from `startTrack`/`endTrack`; the MuseScore 3 staff properties are undefined in MuseScore 4)
- `getCursorInfo` beat computation (via `measure.timesigActual`)
- Docs: the MuseScore plugins directory is `~/Documents/MuseScore4/Plugins` on every OS (previously claimed `%APPDATA%` on Windows)

### Security

- Commands that crash MuseScore Studio 4.7.4 outright (`setBarline`, `addChordSymbol`, `addDynamic`) are gated behind an explicit `__experimental` flag and refused by the MCP tools
- Commands that silently corrupt the score in MuseScore Studio 4.7.4 (`setKeySignature`, `setTempo`) are guarded with explanatory errors
- `exportScore` rejects the `mscz` format (writes a 0-byte file and blocks MuseScore with a modal dialog in 4.7.4)

- Skill now asks user for missing metadata (title, composer, arranger, subtitle, copyright) instead of silently using defaults
- Chord repetition intervals are context-aware: divides phrase length evenly instead of fixed "every 4 bars"
- Skill documents volta brackets (1st/2nd endings) via `spanner.RepeatBracket`
- Skill documents MuseScore subtitle/arranger display limitation (known issue, data is in MusicXML)
- Dependabot: bumped setup-uv 7.3.0→7.3.1, upload-artifact 4→7, download-artifact 4→8
