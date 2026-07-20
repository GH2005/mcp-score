# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/).

## [Unreleased]

### Added

- Score generation via Claude Code skill (music21 -> MusicXML)
- MCP server with 23 tools for live score manipulation (MuseScore, Dorico, Sibelius)
- Multi-bridge architecture: MuseScore QML plugin, Dorico Remote Control, Sibelius Connect
- MuseScore 4 QML plugin with WebSocket bridge (22 commands, native api.websocketserver transport)
- CLI install commands: `mcp-score install-skill`, `mcp-score install-plugin`
- Comprehensive test suite (229 tests: 137 mocked + 92 live against a running MuseScore)
- Full documentation (architecture, reference, getting-started)
- GitHub security: CodeQL scanning, branch protection
- Score metadata: subtitle (movementName), arranger (Contributor), copyright support
- Prompt request PR workflow in CONTRIBUTING.md
- Ground-truth read path: `export_live_score` tool + plugin `exportScore` command snapshot the live score to MusicXML, parsed via `src/mcp_score/musicxml.py` (music21)
- Composition tools: `add_live_notes`, `process_live_sequence`, `set_live_time_signature`, `append_live_measures`
- Live test suite (`tests/live/`, `pytest -m live`) verifying every tool and wire command against a running MuseScore by diffing MusicXML snapshots
- Plugin `apiProbe` diagnostic command and `pluginVersion` reporting in `getScore`
- Agent playbook (`docs/agent-playbook.md`): verified MuseScore support matrix and usage patterns

### Changed

- Plugin transport ported to MuseScore's native `api.websocketserver` (the QtWebSockets QML module does not exist in MuseScore 4's plugin runtime)
- `read_passage`/`get_measure_content` rewritten onto the export-based ground-truth path for MuseScore (the cursor walk saw at most the first element of a measure)
- `transpose_passage` sends a single ranged `transpose` message; the plugin transposes note-by-note with tonal-pitch-class spelling (`curScore.transpose()` does not exist in MuseScore 4, and `selectRange` produces no active selection there)
- Plugin tracks the intra-measure cursor position so consecutive `addNote` commands accumulate instead of overwriting
- Plugin version bumped to 0.2.0

### Fixed

- Consecutive `addNote` steps inside `processSequence` no longer overwrite each other (shared cursor threading)
- `getScore` parts report staff ranges again (derived from `startTrack`/`endTrack`; the MuseScore 3 staff properties are undefined in MuseScore 4)
- `getCursorInfo` beat computation (via `measure.timesigActual`) and note names (derived from tpc + pitch)
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
