# Architecture

> Explanation -- how mcp-score is structured and why.

## Overview

mcp-score provides two complementary approaches for AI-driven music notation:

1. **Score generation** via Claude Code skill -- Claude writes music21 Python scripts that export MusicXML, openable in any notation software
2. **Live manipulation** via MCP server -- read from and write to a running score application (MuseScore, Dorico, or Sibelius) through a WebSocket bridge

## System diagram

```
+---------------------------------------------+
|  Claude (or any LLM via MCP)                |
|  "Create a big band score, AABA, Bb..."     |
+--------+--------------------+---------------+
         |                    |
    Skill invocation     MCP protocol (stdio)
         |                    |
         v                    v
+----------------+   +-----------------------------+
| score-generate |   | Python MCP Server           |
| Claude Skill   |   | (src/mcp_score/)            |
|                |   |                             |
| Writes music21 |   | tools/connection.py (8)     |
| Python script  |   | tools/analysis.py   (4)     |
| -> MusicXML    |   | tools/manipulation.py (11)  |
+----------------+   |                             |
                     | bridge/                     |
                     |   base.py (ScoreBridge)     |
                     |   remote_control.py         |
                     |   musescore.py              |
                     |   dorico.py / sibelius.py   |
                     +------+--------+--------+----+
                            |        |        |
                WebSocket   |        |        | WebSocket
           (ws://:8765)     |        |        | (ws://:1898)
                            |        |        |
            +---------------v-+  +---v------+ +--v-----------+
            | MuseScore QML   |  | Dorico   | | Sibelius     |
            | Plugin          |  | Remote   | | Connect      |
            | (bridge.qml)    |  | Control  | | (built-in)   |
            +-----------------+  | :4560    | | 900+ cmds    |
                                 +----------+ +--------------+
```

## Multi-bridge design

mcp-score supports multiple score notation applications through a common bridge abstraction. Only one bridge is active at a time -- connecting to a new application automatically disconnects the previous one.

### Bridge abstraction

`ScoreBridge` (in `bridge/base.py`) defines the common interface that all MCP tools depend on. The bridge hierarchy:

```
ScoreBridge (ABC)
├── MuseScoreBridge          -- custom protocol for MuseScore QML plugin
└── RemoteControlBridge      -- shared handshake/command protocol
    ├── DoricoBridge         -- Dorico defaults (port 4560)
    └── SibeliusBridge       -- Sibelius defaults (port 1898)
```

- `MuseScoreBridge` -- connects to the MuseScore QML plugin's WebSocket server (different protocol)
- `RemoteControlBridge` (in `bridge/remote_control.py`) -- shared protocol logic for Dorico and Sibelius: handshake with session tokens, command formatting, reconnection, barline mapping, and limitation messages
- `DoricoBridge` -- thin subclass providing Dorico-specific defaults
- `SibeliusBridge` -- thin subclass providing Sibelius-specific defaults

### Bridge registry

`bridge/__init__.py` manages the active bridge:

- `get_active_bridge()` -- returns the currently connected bridge (or None)
- `set_active_bridge()` -- sets which bridge is active
- Tools call `connected_bridge()` from `tools/__init__.py`, which returns the active bridge only if it's connected

### Remote Control protocol (shared by Dorico and Sibelius)

Dorico 4+ and Sibelius 2024.3+ both implement the same "Remote Control" WebSocket protocol. The shared logic lives in `bridge/remote_control.py`.

**Handshake protocol:**

1. Client opens WebSocket to the application's port (Dorico: 4560, Sibelius: 1898)
2. Client sends connect message with `clientName` and `handshakeVersion`
3. Application shows a dialog asking the user to approve the connection
4. Application responds with a session token
5. Client sends `acceptsessiontoken` with the received token
6. Application responds with `{"code": "kConnected"}`

Session tokens can be cached and reused for reconnection (the application skips the approval dialog when a valid cached token is provided).

**Dorico-specific notes:**

- Default port 4560, configurable in Dorico preferences
- No plugin needed -- Dorico IS the server

**Sibelius-specific notes:**

- Default port 1898, configurable
- Requires Sibelius Ultimate tier
- No plugin needed -- Sibelius IS the server

## Capabilities and limitations

The Remote Control WebSocket API (shared by Dorico and Sibelius) is fundamentally a **command execution and UI state observation** layer. It can trigger any action the application can perform (equivalent to pressing menu items or key commands) and read the UI state. But it cannot read musical content or perform operations that require text input through popovers.

### What the WebSocket API can do

| Capability                                                     |               MuseScore               |          Dorico          |         Sibelius         |
| -------------------------------------------------------------- | :-----------------------------------: | :----------------------: | :----------------------: |
| Execute commands (undo, navigation, barlines, rehearsal marks) |                  Yes                  |   Yes (~994 commands)    |   Yes (900+ commands)    |
| Get application status                                         |                  Yes                  |           Yes            |           Yes            |
| Get selection properties                                       |                  Yes                  |           Yes            |           Yes            |
| Get flows and layouts                                          |                  N/A                  |           Yes            |         Unknown          |
| Set barlines                                                   |      No (crashes 4.7.4; guarded)      |           Yes            |           Yes            |
| Add rehearsal marks                                            |        Yes (with custom text)         | Yes (auto-numbered only) | Yes (auto-numbered only) |
| Navigate to measure                                            |                  Yes                  |           Yes            |           Yes            |
| Read note content                                              |  Yes (exportScore + MusicXML parse)   |            No            |            No            |
| Set key signature / tempo                                      | No (corrupt insert in 4.7.4; guarded) |            No            |            No            |
| Undo                                                           |      No (silent no-op in 4.7.4)       |           Yes            |           Yes            |
| Export score snapshot (MusicXML)                               |           Yes (exportScore)           |            No            |            No            |
| Read cursor position                                           |      Yes (measure, beat, staff)       | Limited (UI state only)  | Limited (UI state only)  |

### What the WebSocket API cannot do (and why)

These are **upstream API constraints** in Dorico and Sibelius, not mcp-score limitations:

**Chord symbols, key signatures, tempo marks** -- In Dorico and Sibelius, these are entered through popovers (text input dialogs). The WebSocket API can execute commands but has no mechanism to interact with popovers or provide text input. There is no `SetKeySignature`, `SetTempo`, or `AddChordSymbol` command in either application's API.

**Read arbitrary score content** (Dorico/Sibelius) -- The WebSocket API reports on UI state and selection properties, but cannot enumerate notes, articulations, or other musical elements at arbitrary positions. MuseScore's custom QML plugin provides deeper access because it runs inside the application with full scripting API access.

**Staff navigation** (Dorico/Sibelius) -- The API operates on the current selection. There is no command to programmatically move the selection to a specific staff.

**MusicXML export** (Dorico/Sibelius) -- Their WebSocket APIs cannot export score content programmatically. The MuseScore plugin CAN: its `exportScore` command snapshots the live score to MusicXML, which is what makes ground-truth reads possible there.

### The future path

The WebSocket API limitations can be overcome with **application-native scripting plugins** that run inside the application (like the existing MuseScore QML plugin):

- **Sibelius**: A ManuScript plugin can access the full object model -- notes, bars, staves, key signatures, text, chord symbols. ManuScript has file I/O (`ReadTextFile`/`WriteTextFile`) for communicating with an external bridge process. Requires Sibelius Ultimate tier.
- **Dorico**: Lua scripts can execute commands and access some internal state, though Dorico's Lua API is undocumented. Steinberg has acknowledged that expanded scripting is planned but unscheduled.

These bridge plugins would complement the WebSocket API (not replace it), handling the operations that popovers block today.

## Why two approaches?

**Generation is best as a skill.** Claude writes a complete music21 script in one shot, giving it full access to the entire music21 API. This is faster (one script vs dozens of MCP tool calls) and more flexible (no API surface to limit). A skill that teaches Claude music21 patterns produces better results than a curated set of MCP tools.

**Manipulation is best as MCP.** Reading from and writing to a live score application requires a persistent WebSocket connection and state management. MCP provides the right abstraction for this -- tools that Claude can call to inspect and modify the live score.

## Package structure

```
src/mcp_score/
  __init__.py           Package root
  app.py                Shared FastMCP instance ("mcp-score")
  cli.py                CLI entry point (serve, install-skill, install-plugin)
  server.py             MCP server -- imports tool modules, runs FastMCP
  tools/
    __init__.py         Shared helpers: connected_bridge(), to_json(), etc.
    connection.py       8 tools: connect/disconnect MuseScore, Dorico & Sibelius, ping, info
    analysis.py         4 tools: read_passage, get_measure_content,
                                 get_selection_properties, export_live_score
    manipulation.py     11 tools: rehearsal marks, notes, time signatures, measures,
                                 sequences, transpose, undo + guarded chords/barlines/keys/tempo
  musicxml.py           MusicXML parsing/diffing (ground-truth read path)
  bridge/
    __init__.py         Bridge registry (get_active_bridge, set_active_bridge)
    base.py             ScoreBridge abstract base class
    remote_control.py   RemoteControlBridge -- shared protocol for Dorico & Sibelius
    musescore.py        MuseScoreBridge -- WebSocket client for MuseScore plugin
    dorico.py           DoricoBridge -- thin subclass (Dorico defaults)
    sibelius.py         SibeliusBridge -- thin subclass (Sibelius defaults)
  musescore/
    mcp-score-bridge.qml  MuseScore QML plugin (WebSocket server)

.claude/skills/
  score-generate/       Claude Code skill for score generation
    SKILL.md            Skill instructions + music21 patterns
    references/         Instrument reference, etc.

tests/                  pytest tests (mocked; CI-safe)
tests/live/             live suite against a running MuseScore (pytest -m live)
docs/                   Documentation (Diataxis structure; agent-playbook.md is the
                        verified MuseScore support matrix)
```

## Module responsibilities

### `app.py` -- shared FastMCP instance

Creates the single `FastMCP("mcp-score")` instance that all tool modules import. Avoids circular imports: tool modules import `mcp` from `app`, and `server.py` imports `mcp` from `app` plus triggers tool registration via side-effect imports.

### `cli.py` -- CLI entry point

Provides subcommands: `serve` (default, runs MCP server), `run` (execute a Python script with music21 available), `install-skill` (copies skill to `~/.claude/skills/`), `install-plugin` (copies QML plugin to MuseScore plugins directory), `install` (both).

### `server.py` -- MCP server

Imports the three tool modules (connection, analysis, manipulation) to register their `@mcp.tool()` decorators, then exposes the `main()` function. Called by `cli.py serve`.

### `bridge/base.py` -- abstract interface

`ScoreBridge` defines the common interface: `connect()`, `disconnect()`, `send_command()`, `ping()`, `get_score()`, `go_to_measure()`, etc. Concrete bridges implement this for each application.

### `bridge/musescore.py` -- MuseScore bridge

`MuseScoreBridge(ScoreBridge)` connects to the MuseScore QML plugin. Features auto-connect on first command, automatic reconnect on connection loss, and typed convenience methods for all plugin commands.

### `bridge/remote_control.py` -- shared Remote Control protocol

`RemoteControlBridge(ScoreBridge)` implements the WebSocket protocol shared by Dorico and Sibelius: handshake with session tokens, command formatting, send-with-reconnect, barline mapping, and limitation messages for unsupported operations. Uses `self.application_name` in all user-facing messages for proper attribution.

### `bridge/dorico.py` -- Dorico bridge

`DoricoBridge(RemoteControlBridge)` -- thin subclass that provides Dorico-specific defaults (port 4560, application name "Dorico"). All protocol logic is inherited from `RemoteControlBridge`.

### `bridge/sibelius.py` -- Sibelius bridge

`SibeliusBridge(RemoteControlBridge)` -- thin subclass that provides Sibelius-specific defaults (port 1898, application name "Sibelius"). All protocol logic is inherited from `RemoteControlBridge`. Requires Sibelius Ultimate tier.

### `bridge/__init__.py` -- bridge registry

Manages which bridge is active. `get_active_bridge()` returns the current bridge; `set_active_bridge()` switches it. Connection tools call these to manage the active bridge lifecycle.

## MCP tools (23 total)

### Connection (8 tools)

| Tool                        | Purpose                                        |
| --------------------------- | ---------------------------------------------- |
| `connect_to_musescore`      | Connect to MuseScore (configurable host/port)  |
| `disconnect_from_musescore` | Close the MuseScore connection                 |
| `connect_to_dorico`         | Connect to Dorico Remote Control API           |
| `disconnect_from_dorico`    | Close the Dorico connection                    |
| `connect_to_sibelius`       | Connect to Sibelius Connect API                |
| `disconnect_from_sibelius`  | Close the Sibelius connection                  |
| `get_live_score_info`       | Get info about the open score (any app)        |
| `ping_score_app`            | Check if connected app is responsive (any app) |

### Analysis (4 tools)

| Tool                       | Purpose                                              |
| -------------------------- | ---------------------------------------------------- |
| `read_passage`             | Read a range of measures (ground truth on MuseScore) |
| `get_measure_content`      | Read a specific measure and staff (ground truth)     |
| `get_selection_properties` | Get properties of the current selection              |
| `export_live_score`        | Snapshot the live score to a file (MuseScore)        |

### Manipulation (11 tools)

| Tool                      | Purpose                                               |
| ------------------------- | ----------------------------------------------------- |
| `add_live_rehearsal_mark` | Add a rehearsal mark                                  |
| `add_live_notes`          | Write a run of notes atomically (MuseScore)           |
| `set_live_time_signature` | Set the time signature (MuseScore)                    |
| `append_live_measures`    | Append empty measures (MuseScore)                     |
| `process_live_sequence`   | Batch plugin actions in one undo group (MuseScore)    |
| `transpose_passage`       | Transpose by semitones (note-by-note on MuseScore)    |
| `add_live_chord_symbol`   | Add a chord symbol (guarded on MuseScore: crash)      |
| `set_live_barline`        | Set a barline type (guarded on MuseScore: crash)      |
| `set_live_key_signature`  | Set the key signature (guarded on MuseScore: corrupt) |
| `set_live_tempo`          | Set the tempo (guarded on MuseScore: corrupt)         |
| `undo_last_action`        | Undo the last action (silent no-op on MuseScore)      |

## Key design decisions

### Single server, multiple bridges

One MCP server supports multiple score applications through the bridge abstraction. Only one bridge is active at a time -- this avoids confusion about which application a tool operates on. Connecting to a new application automatically disconnects the previous one.

### MusicXML as interchange format

MusicXML 4.0 is the standard interchange format, supported by 270+ applications including MuseScore, Dorico, and Sibelius. We do NOT generate `.mscz`/`.mscx` -- undocumented and version-fragile.

### music21 for score generation

music21 (MIT, Python) handles transposing instruments, voice leading, and MusicXML export. Used by the score-generate skill.

### WebSocket bridges for live manipulation

All three supported applications use WebSocket for communication, but the protocols differ:

- **MuseScore**: QML plugin runs inside MuseScore, opens a WebSocket server on port 8765. JSON messages with `command` and `params` fields. Custom protocol -- implemented directly in `MuseScoreBridge`.
- **Dorico & Sibelius**: Both use the same "Remote Control" protocol with `message`/`commandName` fields and session token handshake. Shared logic lives in `RemoteControlBridge`; thin subclasses provide application-specific defaults (port, name).

### Ground-truth reads on MuseScore

MuseScore 4's plugin cursor API cannot reliably report score contents (chords, voices, and anything past the first element of a measure are invisible to it), and several of its edit APIs fail silently. Reads therefore go through MuseScore's own exporter: the plugin's `exportScore` command snapshots the live score to MusicXML, which is parsed with music21 (`src/mcp_score/musicxml.py`). The committed live test suite (`tests/live/`) verifies every command against these snapshots; commands MuseScore Studio 4.7.4 cannot execute safely are guarded rather than left to crash or corrupt. See [agent-playbook.md](agent-playbook.md).

### Server does not call LLMs

The MCP server provides primitives. Claude is the musical intelligence.

## Dependencies

| Dependency   | Purpose                                   |
| ------------ | ----------------------------------------- |
| `mcp[cli]`   | MCP SDK (FastMCP server framework)        |
| `music21`    | Music theory library, MusicXML generation |
| `websockets` | WebSocket client for bridge connections   |
