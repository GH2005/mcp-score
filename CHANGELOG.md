# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/).

## [Unreleased]

### Added

- Score generation via Claude Code skill (music21 -> MusicXML)
- MCP server with 28 tools for live score manipulation (MuseScore, Dorico, Sibelius)
- Multi-bridge architecture: MuseScore QML plugin, Dorico Remote Control, Sibelius Connect
- MuseScore 4 QML plugin with WebSocket bridge (23 commands, native api.websocketserver transport)
- CLI install commands: `mcp-score install-skill`, `mcp-score install-plugin`
- Comprehensive test suite (388 tests: 282 mocked + 106 live against a running MuseScore)
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
- `voice_progression` tool: a chord progression voiced into independent parts by music21's figured-bass solver, which searches the voicings that satisfy the classical voice-leading rules. Returns the first rule-satisfying solution deterministically, with the solution count, entries shaped for one staff or split across a grand staff, and -- when nothing satisfies the rules -- the rules that would unblock it (needs no score connection)
- `transform_passage` tool: `invert` (diatonic mirror around an axis note, re-pitching in place), `retrograde` (pitches and rhythm reversed), and `sequence` (the motif repeated into the following measures, each copy shifted by scale steps). Retrograde and sequence rewrite the passage note by note and refuse anything the wire cannot reproduce -- ties, tuplets, grace notes, a meter change, or a voice that does not fill every bar
- `realize_ornament` tool: writes out a trill, mordent, inverted mordent, turn, or inverted turn as the notes it stands for, key-aware and summing to exactly the duration of the note it replaces (needs no score connection)
- `transpose_passage` gained diatonic motion: `degrees` plus `key` moves a passage by scale steps and keeps it in the key (`degrees=2` is "up a third"), reporting every chromatic note it pulled onto the scale. `semitones` remains the chromatic path; exactly one of the two is required
- `realize_harmony` reports `metadata`: root, bass, inversion, quality, and the key a secondary function tonicizes
- Snapshots record a note's tie type, so the transformations that re-enter music can refuse a tied passage instead of re-attacking the far side of the tie

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

- Transposition off the end of the MIDI range is refused instead of silently landing octaves away. music21's `Pitch.midi` folds an out-of-range pitch back inside 0-127, so the existing range guard could never fire: transposing a top-of-range note up an octave wrote it an octave _down_. Range checks now read pitch space directly
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
