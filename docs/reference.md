# Tool reference

> Reference -- complete list of MCP tools provided by mcp-score.

Score generation is handled by the `score-generate` Claude Code skill (not MCP tools). See the [skill documentation](../README.md#score-generation-skill) for usage.

The MCP server provides 23 tools across 3 categories for live score manipulation. All tools work with any connected application — MuseScore, Dorico, or Sibelius — though some operations are limited or unavailable depending on what the application's API can execute safely. For MuseScore, the [agent playbook](agent-playbook.md) is the verified support matrix: several commands are guarded because MuseScore Studio 4.7.4 crashes or silently corrupts the score when they run.

## Connection tools (8)

Manage WebSocket bridges to live score notation applications. Each application has its own connect and disconnect pair, plus two shared tools that work with whichever application is currently active.

Connecting to a new application automatically disconnects any existing active connection.

### `connect_to_musescore`

Connect to a running MuseScore instance. The MCP Score Bridge QML plugin must be installed and running in MuseScore.

| Parameter | Type  | Default       | Description    |
| --------- | ----- | ------------- | -------------- |
| `host`    | `str` | `"localhost"` | WebSocket host |
| `port`    | `int` | `8765`        | WebSocket port |

### `disconnect_from_musescore`

Disconnect from MuseScore. No parameters.

### `connect_to_dorico`

Connect to a running Dorico instance via its built-in Remote Control API. Dorico 4+ has a built-in WebSocket server — no plugin required. The Remote Control API must be enabled in Dorico's preferences.

| Parameter | Type  | Default       | Description                       |
| --------- | ----- | ------------- | --------------------------------- |
| `host`    | `str` | `"localhost"` | WebSocket host                    |
| `port`    | `int` | `4560`        | WebSocket port (Dorico's default) |

### `disconnect_from_dorico`

Disconnect from Dorico. No parameters.

### `connect_to_sibelius`

Connect to a running Sibelius instance via Sibelius Connect. Sibelius 2024.3+ has a built-in WebSocket server — no plugin required. Requires the Sibelius Ultimate tier. The port is configurable in Sibelius's preferences.

| Parameter | Type  | Default       | Description                                 |
| --------- | ----- | ------------- | ------------------------------------------- |
| `host`    | `str` | `"localhost"` | WebSocket host                              |
| `port`    | `int` | `1898`        | WebSocket port (Sibelius Connect's default) |

### `disconnect_from_sibelius`

Disconnect from Sibelius. No parameters.

### `get_live_score_info`

Get information about the currently open score in the connected application. No parameters. Requires an active connection — use one of the `connect_to_*` tools first.

### `ping_score_app`

Check if the connected score application is responsive. No parameters. Does not auto-connect — returns an error if not already connected.

---

## Analysis tools (4)

Read musical content from the connected score application. All analysis tools require an active connection.

**Note on MuseScore:** `read_passage` and `get_measure_content` are ground-truth reads: the live score (including unsaved edits) is exported to MusicXML via the plugin's `exportScore` command and parsed with music21, so every note, chord, rest, voice, and annotation is reported accurately.

**Note on Dorico and Sibelius:** These applications expose a Remote Control WebSocket API that returns application status rather than detailed note content. `read_passage` and `get_measure_content` return a `warning` field when connected to Dorico or Sibelius. `get_selection_properties` is the recommended tool for reading score data with those applications.

### `read_passage`

Read musical content from a range of measures. With MuseScore, returns every note, chord, rest, and annotation per measure and staff (export-based ground truth).

| Parameter       | Type          | Default    | Description                                       |
| --------------- | ------------- | ---------- | ------------------------------------------------- |
| `start_measure` | `int`         | (required) | First measure to read (1-indexed)                 |
| `end_measure`   | `int`         | (required) | Last measure to read (inclusive, 1-indexed)       |
| `staff`         | `int \| None` | `None`     | Staff index (0-indexed). Omit to read all staves. |

Accurate with MuseScore. When connected to Dorico or Sibelius, the response includes a `warning` field explaining the data limitations.

### `get_measure_content`

Read the content of a specific measure and staff. With MuseScore this is an export-based ground-truth read.

| Parameter | Type  | Default    | Description                |
| --------- | ----- | ---------- | -------------------------- |
| `measure` | `int` | (required) | Measure number (1-indexed) |
| `staff`   | `int` | `0`        | Staff index (0-indexed)    |

Accurate with MuseScore. When connected to Dorico or Sibelius, the response includes a `warning` field explaining the data limitations.

### `export_live_score`

Export a snapshot of the live score to a file (MuseScore only). Captures the in-memory score including unsaved edits without touching the user's file — the ground-truth read path.

| Parameter | Type          | Default      | Description                                                                                                   |
| --------- | ------------- | ------------ | ------------------------------------------------------------------------------------------------------------- |
| `path`    | `str \| None` | `None`       | Absolute output path. Defaults to a unique file in the system temp directory (the reply contains the path).   |
| `format`  | `str`         | `"musicxml"` | One of `musicxml`, `mxl`, `xml`, `pdf`, `mid`, `midi`. `mscz` is rejected (broken in MuseScore Studio 4.7.4). |

### `get_selection_properties`

Get properties of the current selection in the connected application. Behaviour varies by application:

- **MuseScore**: Returns cursor position info (measure, beat, staff).
- **Dorico / Sibelius**: Returns names, types, and values of all properties on the selected items via the Remote Control API's `getproperties` message. This is the closest the WebSocket API gets to reading score data, and is the recommended way to inspect content when connected to Dorico or Sibelius.

No parameters. Requires an active connection.

---

## Manipulation tools (11)

Modify the live score in the connected application. All manipulation tools require an active connection.

**MuseScore limitations (verified against MuseScore Studio 4.7.4):** some plugin commands crash MuseScore outright or silently insert corrupt elements, so the corresponding tools refuse MuseScore connections with an explanatory error:

- `set_live_barline` and `add_live_chord_symbol` — the plugin command **crashes MuseScore**; guarded.
- `set_live_key_signature` and `set_live_tempo` — the plugin inserts a **corrupt element** (wrong key / empty tempo mark); guarded.
- `undo_last_action` — reports ok but **does nothing** in MuseScore (the plugin-context undo is a no-op). Verify edits with reads instead of relying on undo.

**Dorico/Sibelius limitations:** their Remote Control WebSocket API interacts with UI commands rather than the score model directly:

- `add_live_chord_symbol`, `set_live_key_signature`, `set_live_tempo` — return an error (these require popover input the API cannot provide).
- `add_live_rehearsal_mark` — succeeds but ignores the `text` parameter; the application auto-numbers.
- `set_live_barline` — works with the four supported barline types.
- `set_live_time_signature`, `append_live_measures`, `add_live_notes`, `process_live_sequence` — MuseScore only.

### `add_live_rehearsal_mark`

Add a rehearsal mark at the start of the specified measure.

| Parameter | Type  | Description                                        |
| --------- | ----- | -------------------------------------------------- |
| `measure` | `int` | Measure number (1-indexed)                         |
| `text`    | `str` | Rehearsal mark text (e.g. `"A"`, `"B"`, `"Intro"`) |

When connected to Dorico or Sibelius, the `text` parameter is ignored and the application uses its own auto-numbering. The response includes a `warning` field in that case.

### `add_live_chord_symbol`

Add a chord symbol at the start of the specified measure.

| Parameter | Type  | Description                                    |
| --------- | ----- | ---------------------------------------------- |
| `measure` | `int` | Measure number (1-indexed)                     |
| `symbol`  | `str` | Chord symbol (e.g. `"Cmaj7"`, `"Dm7"`, `"G7"`) |

Not supported with any connected application today: Dorico/Sibelius require popover input their API cannot provide, and the MuseScore plugin command crashes MuseScore Studio 4.7.4 (guarded).

### `set_live_barline`

Set a barline type at the end of the specified measure.

| Parameter      | Type  | Description                                                  |
| -------------- | ----- | ------------------------------------------------------------ |
| `measure`      | `int` | Measure number (1-indexed)                                   |
| `barline_type` | `str` | One of `"double"`, `"final"`, `"startRepeat"`, `"endRepeat"` |

Works with Dorico and Sibelius. Disabled for MuseScore (the plugin command crashes MuseScore Studio 4.7.4).

### `set_live_key_signature`

Set the key signature at the specified measure.

| Parameter | Type  | Description                                                                          |
| --------- | ----- | ------------------------------------------------------------------------------------ |
| `measure` | `int` | Measure number (1-indexed)                                                           |
| `fifths`  | `int` | Sharps (positive) or flats (negative): `0` = C major, `2` = D major, `-3` = Eb major |

Not supported with any connected application today: Dorico/Sibelius require popover input their API cannot provide, and MuseScore Studio 4.7.4 inserts a corrupt key signature (guarded).

### `set_live_tempo`

Set the tempo at the specified measure.

| Parameter | Type          | Default    | Description                                         |
| --------- | ------------- | ---------- | --------------------------------------------------- |
| `measure` | `int`         | (required) | Measure number (1-indexed)                          |
| `bpm`     | `int`         | (required) | Beats per minute                                    |
| `text`    | `str \| None` | `None`     | Optional display text (e.g. `"Swing"`, `"Allegro"`) |

Not supported with any connected application today: Dorico/Sibelius require popover input their API cannot provide, and MuseScore Studio 4.7.4 inserts an empty tempo mark (guarded).

### `transpose_passage`

Transpose a passage by a number of semitones.

| Parameter       | Type  | Description                                             |
| --------------- | ----- | ------------------------------------------------------- |
| `start_measure` | `int` | First measure (1-indexed)                               |
| `end_measure`   | `int` | Last measure (inclusive, 1-indexed)                     |
| `staff`         | `int` | Staff index (0-indexed)                                 |
| `semitones`     | `int` | Semitones to transpose (positive = up, negative = down) |

MuseScore only. Implemented note-by-note with correct enharmonic spelling (the plugin walks the range with a cursor; `curScore.transpose()` does not exist in MuseScore 4).

### `undo_last_action`

Undo the last action in the connected score application. No parameters.

**Broken with MuseScore** (Studio 4.7.4): the reply says ok but nothing is undone — the plugin-context undo is a no-op. Verify edits with `read_passage` and correct mistakes with explicit edits instead. Works with Dorico and Sibelius via their `Edit.Undo` command.

### `set_live_time_signature`

Set the time signature at a measure (MuseScore only). Re-bars the music from that measure onward.

| Parameter     | Type  | Description                  |
| ------------- | ----- | ---------------------------- |
| `measure`     | `int` | Measure number (1-indexed)   |
| `numerator`   | `int` | Beats per measure (e.g. `3`) |
| `denominator` | `int` | Beat unit (e.g. `4` for 3/4) |

### `append_live_measures`

Append empty measures to the end of the score (MuseScore only).

| Parameter | Type  | Default | Description                        |
| --------- | ----- | ------- | ---------------------------------- |
| `count`   | `int` | `1`     | Number of measures to append (>=1) |

### `add_live_notes`

Write a run of notes starting at beat 1 of a measure (MuseScore only). Notes are written consecutively — each advances the insertion point by its duration, spilling into following measures — and REPLACE existing content at those beats. Executes atomically via the plugin's `processSequence`.

| Parameter | Type         | Description                                                                                       |
| --------- | ------------ | ------------------------------------------------------------------------------------------------- |
| `measure` | `int`        | Starting measure (1-indexed)                                                                      |
| `staff`   | `int`        | Staff index (0-indexed)                                                                           |
| `notes`   | `list[dict]` | Each `{"pitch": <0-127 MIDI>, "numerator": 1, "denominator": 4}` (duration defaults to a quarter) |

### `process_live_sequence`

Execute a batch of plugin actions in one undo group (MuseScore only). Each step is `{"action": <name>, "params": {...}}`; supported actions: `ping`, `goToMeasure`, `goToStaff`, `addNote`, `addRehearsalMark`, `setTimeSignature`, `appendMeasures`, `selectCurrentMeasure`, `selectCustomRange`, `transpose`. Steps naming crash- or corruption-prone actions are rejected.

Note: rollback on failure is broken in MuseScore Studio 4.7.4 (the plugin undo is a no-op), so steps before a failure stay applied; the reply carries `failedIndex`/`failedAction`.

| Parameter | Type         | Description                                  |
| --------- | ------------ | -------------------------------------------- |
| `steps`   | `list[dict]` | Ordered list of `{"action", "params"}` dicts |
