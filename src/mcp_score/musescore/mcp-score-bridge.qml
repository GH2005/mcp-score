// MuseScore QML Plugin -- WebSocket server for mcp-score bridge.
//
// Install: copy to MuseScore's Plugins directory, enable via Plugin Manager.
//
// Opens a WebSocket server inside MuseScore, allowing the mcp-score Python
// MCP server to read from and write to the active score by sending JSON
// commands and receiving JSON responses.
//
// Protocol: each WebSocket message is a JSON object with a "command" field
// and optionally a "params" field. The response is always a JSON object with
// either a "result" field (on success) or an "error" field (on failure).
//
// Supported commands:
//   ping, getScore, getCursorInfo, goToMeasure, goToStaff, addNote,
//   addRehearsalMark, setBarline, setKeySignature, setTimeSignature,
//   setTempo, addChordSymbol, addDynamic, appendMeasures,
//   selectCurrentMeasure, selectCustomRange, transpose, undo,
//   processSequence, exportScore, newScore, apiProbe
//
// setBarline, addChordSymbol, and addDynamic crash MuseScore Studio
// 4.7.4 (newElement + cursor.add is fatal for those element types) and
// therefore require an explicit "__experimental": true parameter.
// setKeySignature and setTempo insert corrupt elements in 4.7.4 (the
// clone made by cursor.add loses the assigned values). newScore creates
// the score in a window this bridge cannot control. See
// docs/agent-playbook.md for the verified support matrix.

import QtQuick 2.9
import MuseScore 3.0

MuseScore {
    id: root
    menuPath: "Plugins.MCP Score Bridge"
    description: "WebSocket bridge for mcp-score MCP server"
    version: "0.2.0"

    // Keep the plugin running after onRun (required for persistent server).
    pluginType: "dock"
    dockArea: "bottom"
    implicitWidth: 0
    implicitHeight: 0

    // ===================================================================
    // Constants
    // ===================================================================

    readonly property int serverPort: 8765
    readonly property string serverHost: "localhost"
    readonly property string logPrefix: "[mcp-score]"

    // MuseScore internal tick counts (from fraction.h).
    readonly property int ticksPerWholeNote: 1920
    readonly property real secondsPerMinute: 60.0

    // Key signature bounds (circle of fifths).
    readonly property int minFifths: -7
    readonly property int maxFifths: 7

    // ===================================================================
    // Lookup tables
    // ===================================================================

    // Barline type string -> MuseScore enum value.
    readonly property var barlineTypes: ({
        "normal":         1,
        "double":         2,
        "startRepeat":    4,
        "endRepeat":      8,
        "endStartRepeat": 16,
        "final":          32,
        "dashed":         64,
        "dotted":         128,
        "tick":           256,
        "short":          512
    })

    // Dynamic marking -> MIDI velocity.
    readonly property var dynamicVelocities: ({
        "pppp": 10,  "ppp": 25,  "pp": 36,  "p": 49,   "mp": 64,
        "mf": 80,    "f": 96,    "ff": 112,  "fff": 120, "ffff": 127,
        "fp": 96,    "sfz": 112, "sffz": 120, "sfp": 112, "rfz": 112,
        "fz": 112
    })

    // Semitone -> diatonic interval (within one octave).
    // Used for chromatic transposition with correct enharmonic spelling.
    readonly property var semitoneToDiatonic: [0, 1, 1, 2, 2, 3, 3, 4, 5, 5, 6, 6]

    // ===================================================================
    // Internal cursor state
    // ===================================================================

    // Logical cursor position, maintained across commands. The MuseScore
    // Cursor object is re-created from this state for each command.

    property int cursorMeasure: 1   // 1-indexed measure number
    property int cursorStaff: 0     // 0-indexed staff index
    property int cursorVoice: 0     // voice (always 0 for now)
    property int cursorTick: -1     // intra-measure tick (-1 = measure start);
                                    // advanced by addNote so consecutive notes
                                    // accumulate instead of overwriting

    // ===================================================================
    // Command dispatch
    // ===================================================================

    function handleMessage(message) {
        var request;
        try {
            request = JSON.parse(message);
        } catch (e) {
            return { error: "Invalid JSON: " + e.message };
        }

        var command = request.command;
        var params = request.params || {};

        if (!command) {
            return { error: "Missing 'command' field" };
        }

        console.log(logPrefix, "Command:", command);

        try {
            switch (command) {
                case "ping":                return handlePing();
                case "getScore":            return handleGetScore();
                case "getCursorInfo":       return handleGetCursorInfo();
                case "goToMeasure":         return handleGoToMeasure(params);
                case "goToStaff":           return handleGoToStaff(params);
                case "addNote":             return handleAddNote(params);
                case "addRehearsalMark":    return handleAddRehearsalMark(params);
                case "setBarline":          return handleSetBarline(params);
                case "setKeySignature":     return handleSetKeySignature(params);
                case "setTimeSignature":    return handleSetTimeSignature(params);
                case "setTempo":            return handleSetTempo(params);
                case "addChordSymbol":      return handleAddChordSymbol(params);
                case "addDynamic":          return handleAddDynamic(params);
                case "appendMeasures":      return handleAppendMeasures(params);
                case "selectCurrentMeasure": return handleSelectCurrentMeasure();
                case "selectCustomRange":   return handleSelectCustomRange(params);
                case "transpose":           return handleTranspose(params);
                case "undo":                return handleUndo();
                case "processSequence":     return handleProcessSequence(params);
                case "exportScore":         return handleExportScore(params);
                case "newScore":            return handleNewScore(params);
                case "apiProbe":            return handleApiProbe();
                default:
                    return { error: "Unknown command: " + command };
            }
        } catch (e) {
            console.log(logPrefix, "Error handling '" + command + "':", e.message);
            return { error: e.message || String(e) };
        }
    }

    // ===================================================================
    // Guard helpers (reduce repetition in handlers)
    // ===================================================================

    /// Returns an error object if no score is open, or null if OK.
    function requireScore() {
        if (!curScore) {
            return { error: "No score is currently open" };
        }
        return null;
    }

    /// Returns a positioned cursor, or an error object if it cannot be created.
    function requireCursor() {
        var scoreErr = requireScore();
        if (scoreErr) return { cursor: null, error: scoreErr };

        var cursor = positionedCursor();
        if (!cursor) return { cursor: null, error: { error: "Could not position cursor" } };

        return { cursor: cursor, error: null };
    }

    // ===================================================================
    // Cursor positioning
    // ===================================================================

    /// Create a MuseScore Cursor at the current logical position.
    /// Positions at the start of cursorMeasure, then seeks forward to
    /// cursorTick when one is recorded (so consecutive addNote commands
    /// continue where the previous one ended instead of overwriting).
    function positionedCursor() {
        if (!curScore) return null;
        var cursor = curScore.newCursor();
        cursor.staffIdx = cursorStaff;
        cursor.voice = cursorVoice;
        cursor.rewind(Cursor.SCORE_START);

        for (var i = 1; i < cursorMeasure; i++) {
            cursor.nextMeasure();
        }
        if (cursorTick >= 0) {
            while (cursor.tick < cursorTick && cursor.next()) {
                // seek forward within the score to the recorded tick
            }
        }
        return cursor;
    }

    /// Navigate a raw cursor to a specific 1-indexed measure number.
    function advanceCursorToMeasure(cursor, measureNumber) {
        cursor.rewind(Cursor.SCORE_START);
        for (var i = 1; i < measureNumber; i++) {
            cursor.nextMeasure();
        }
    }

    // ===================================================================
    // Utility helpers
    // ===================================================================

    /// Count the total number of measures in the score.
    function countMeasures() {
        if (!curScore) return 0;
        var cursor = curScore.newCursor();
        cursor.rewind(Cursor.SCORE_START);
        var count = 0;
        while (cursor.measure) {
            count++;
            cursor.nextMeasure();
        }
        return count;
    }

    /// Get the 1-indexed measure number for a given tick position.
    function measureNumberAtTick(tick) {
        if (!curScore) return 0;
        var cursor = curScore.newCursor();
        cursor.rewind(Cursor.SCORE_START);
        var measureNumber = 1;
        while (cursor.measure) {
            var measureStart = cursor.tick;
            cursor.nextMeasure();
            var measureEnd = cursor.measure ? cursor.tick : Infinity;
            if (tick >= measureStart && tick < measureEnd) {
                return measureNumber;
            }
            measureNumber++;
        }
        return measureNumber;
    }

    /// Map a barline type string to the MuseScore enum value, or null.
    function barlineTypeFromString(typeString) {
        var value = barlineTypes[typeString];
        return (value !== undefined) ? value : null;
    }

    /// Parse a value to integer, returning null if the result is NaN.
    function safeParseInt(value) {
        var parsed = parseInt(value);
        return isNaN(parsed) ? null : parsed;
    }

    /// Derive a note name like "C4" or "Eb3" from tpc + MIDI pitch.
    /// note.noteName is undefined in MuseScore 4, so the name is computed:
    /// step letter = "FCGDAEB"[(tpc + 1) % 7], alteration =
    /// floor((tpc + 1) / 7) - 2, octave from the written pitch class.
    function noteNameFromTpcPitch(tpc, pitch) {
        if (tpc === undefined || tpc === null || pitch === undefined)
            return null;
        var steps = "FCGDAEB";
        var step = steps.charAt(((tpc + 1) % 7 + 7) % 7);
        var alteration = Math.floor((tpc + 1) / 7) - 2;
        var naturalPc = { C: 0, D: 2, E: 4, F: 5, G: 7, A: 9, B: 11 }[step];
        var octave = Math.floor((pitch - naturalPc - alteration) / 12) - 1;
        var accidental = "";
        for (var a = 0; a < Math.abs(alteration); a++) {
            accidental += (alteration > 0) ? "#" : "b";
        }
        return step + accidental + octave;
    }

    /// Describe a score element as a plain object for JSON serialization.
    function describeElement(element) {
        if (!element) return null;

        var info = { type: element.type };

        if (element.type === Element.CHORD) {
            var notes = [];
            for (var i = 0; i < element.notes.length; i++) {
                var note = element.notes[i];
                notes.push({
                    pitch: note.pitch,
                    tpc: note.tpc,
                    name: noteNameFromTpcPitch(note.tpc, note.pitch)
                });
            }
            info.notes = notes;
            info.duration = {
                numerator: element.duration.numerator,
                denominator: element.duration.denominator
            };
        } else if (element.type === Element.REST) {
            info.duration = {
                numerator: element.duration.numerator,
                denominator: element.duration.denominator
            };
        } else if (element.type === Element.NOTE) {
            info.pitch = element.pitch;
            info.tpc = element.tpc;
            info.name = noteNameFromTpcPitch(element.tpc, element.pitch);
        }

        return info;
    }

    // ===================================================================
    // Command handlers -- read-only / navigation
    // ===================================================================

    function handlePing() {
        return { result: "pong" };
    }

    /// Create and open a fresh score (becomes curScore). Used for
    /// hermetic test runs and clean composition sessions.
    /// Params: { title?: string, measures?: int }
    function handleNewScore(params) {
        var title = params.title || "MCP scratch";
        var measures = safeParseInt(
            params.measures !== undefined ? params.measures : 32);
        if (measures === null || measures < 1) {
            return { error: "measures must be >= 1" };
        }

        var score = newScore(title, "piano", measures);
        if (!score) {
            return { error: "newScore returned nothing" };
        }
        cursorMeasure = 1;
        cursorStaff = 0;
        cursorTick = -1;
        return {
            result: {
                title: title,
                measures: measures,
                measureCount: countMeasures()
            }
        };
    }

    /// Introspect the MuseScore 4 plugin API: which properties and
    /// functions actually exist at runtime, plus element property
    /// round-trips that never touch the score. Diagnostic only.
    function handleApiProbe() {
        var probe = {};
        probe.pluginVersion = root.version;
        probe.globals = {
            cmd: typeof cmd,
            newScore: typeof newScore,
            newElement: typeof newElement,
            fraction: typeof fraction,
            writeScore: typeof writeScore,
            mscoreVersion: (typeof mscoreVersion !== "undefined") ? String(mscoreVersion) : null
        };

        if (curScore) {
            probe.score = {
                undo: typeof curScore.undo,
                undoRedo: typeof curScore.undoRedo,
                undoStack: typeof curScore.undoStack,
                transpose: typeof curScore.transpose,
                appendMeasures: typeof curScore.appendMeasures,
                selection: typeof curScore.selection,
                title: typeof curScore.title
            };
            if (curScore.parts && curScore.parts.length > 0) {
                var part = curScore.parts[0];
                probe.part = {
                    partName: typeof part.partName,
                    startStaff: typeof part.startStaff,
                    endStaff: typeof part.endStaff,
                    startTrack: typeof part.startTrack,
                    endTrack: typeof part.endTrack,
                    instruments: typeof part.instruments
                };
                if (typeof part.startTrack === "number") {
                    probe.part.startTrackValue = part.startTrack;
                    probe.part.endTrackValue = part.endTrack;
                }
            }
            var cur = curScore.newCursor();
            cur.rewind(Cursor.SCORE_START);
            probe.cursor = {
                timeSignature: typeof cur.timeSignature,
                keySignature: typeof cur.keySignature,
                rewindToTick: typeof cur.rewindToTick,
                next: typeof cur.next,
                prev: typeof cur.prev
            };
            if (cur.measure) {
                probe.measure = {
                    timesigActual: typeof cur.measure.timesigActual,
                    timesigNominal: typeof cur.measure.timesigNominal,
                    firstSegment: typeof cur.measure.firstSegment,
                    lastSegment: typeof cur.measure.lastSegment
                };
                if (cur.measure.timesigActual) {
                    probe.measure.timesigActualValue = {
                        numerator: cur.measure.timesigActual.numerator,
                        denominator: cur.measure.timesigActual.denominator
                    };
                }
            }
        }

        // Element property round-trips: create elements WITHOUT adding
        // them to the score, assign, and read back. Reveals broken
        // property mappings (e.g. KEYSIG key writing the wrong value).
        probe.roundTrips = {};
        try {
            var ks = newElement(Element.KEYSIG);
            ks.key = 2;
            probe.roundTrips.keysigKey = { wrote: 2, read: ks.key };
        } catch (e) {
            probe.roundTrips.keysigKey = { error: e.message || String(e) };
        }
        try {
            var tt = newElement(Element.TEMPO_TEXT);
            tt.text = "probe";
            tt.tempo = 1.5;
            probe.roundTrips.tempoText = {
                wroteText: "probe", readText: tt.text,
                wroteTempo: 1.5, readTempo: tt.tempo
            };
        } catch (e) {
            probe.roundTrips.tempoText = { error: e.message || String(e) };
        }
        try {
            var nt = newElement(Element.NOTE);
            nt.pitch = 61;
            nt.tpc = 21;
            probe.roundTrips.notePitchTpc = {
                wrotePitch: 61, readPitch: nt.pitch,
                wroteTpc: 21, readTpc: nt.tpc
            };
        } catch (e) {
            probe.roundTrips.notePitchTpc = { error: e.message || String(e) };
        }

        return { result: probe };
    }

    /// Write a snapshot of the live in-memory score to disk via writeScore().
    /// Captures unsaved edits without touching the user's own file.
    /// params: { path: "C:/full/path/out.musicxml", format: "musicxml" | ... }
    function handleExportScore(params) {
        var scoreErr = requireScore();
        if (scoreErr) return scoreErr;
        if (!params.path) return { error: "exportScore requires 'path'" };

        var format = params.format || "musicxml";
        if (format === "mscz") {
            return { error: "mscz export is broken in MuseScore Studio " +
                "4.7.4: writeScore produces a 0-byte file, never returns, " +
                "and raises a blocking modal dialog. Use musicxml instead." };
        }
        var ok = writeScore(curScore, params.path, format);
        if (ok !== true) {
            return { error: "writeScore failed for " + params.path +
                " (format " + format + ")" };
        }
        return { result: { written: true, path: params.path, format: format } };
    }

    /// Return metadata about the currently open score.
    function handleGetScore() {
        var scoreErr = requireScore();
        if (scoreErr) return scoreErr;

        var parts = [];
        for (var i = 0; i < curScore.parts.length; i++) {
            var part = curScore.parts[i];
            // Part.startStaff/endStaff are undefined in MuseScore 4;
            // derive them from the track range (4 voices per staff).
            var entry = { name: part.partName };
            if (typeof part.startTrack === "number") {
                entry.startStaff = part.startTrack / 4;
                entry.endStaff = part.endTrack / 4 - 1;
            }
            parts.push(entry);
        }

        var cursor = curScore.newCursor();
        cursor.rewind(Cursor.SCORE_START);

        var keySig = (cursor.keySignature !== undefined) ? cursor.keySignature : null;

        var timeSig = null;
        if (cursor.timeSignature) {
            timeSig = {
                numerator: cursor.timeSignature.numerator,
                denominator: cursor.timeSignature.denominator
            };
        }

        // cursor.timeSignature can be undefined in MuseScore 4; fall
        // back to the first measure's actual time signature.
        if (timeSig === null && cursor.measure && cursor.measure.timesigActual) {
            var actual = cursor.measure.timesigActual;
            if (actual.numerator !== undefined) {
                timeSig = {
                    numerator: actual.numerator,
                    denominator: actual.denominator
                };
            }
        }

        return {
            result: {
                title: curScore.title || "",
                partCount: parts.length,
                parts: parts,
                measureCount: countMeasures(),
                keySignature: keySig,
                timeSignature: timeSig,
                pluginVersion: root.version
            }
        };
    }

    /// Return the current logical cursor position and the element there.
    function handleGetCursorInfo() {
        var req = requireCursor();
        if (req.error) return req.error;
        var cursor = req.cursor;

        var elementInfo = cursor.element ? describeElement(cursor.element) : null;

        // cursor.timeSignature is undefined in MuseScore 4; fall back to
        // the measure's actual time signature when available.
        var beat = null;
        var timeSig = cursor.timeSignature
            || (cursor.measure ? cursor.measure.timesigActual : null);
        if (cursor.measure && timeSig && timeSig.denominator) {
            var measureStartTick = cursor.measure.firstSegment.tick;
            var ticksPerBeat = ticksPerWholeNote / timeSig.denominator;
            beat = Math.floor((cursor.tick - measureStartTick) / ticksPerBeat) + 1;
        }

        return {
            result: {
                measure: cursorMeasure,
                staff: cursorStaff,
                voice: cursorVoice,
                beat: beat,
                tick: cursor.tick,
                element: elementInfo
            }
        };
    }

    /// Move the logical cursor to the specified 1-indexed measure.
    function handleGoToMeasure(params) {
        var scoreErr = requireScore();
        if (scoreErr) return scoreErr;

        if (params.measure === undefined) {
            return { error: "Missing required parameter: measure" };
        }

        var measureNumber = safeParseInt(params.measure);
        if (measureNumber === null) {
            return { error: "Invalid value for measure: " + params.measure };
        }
        var totalMeasures = countMeasures();

        if (measureNumber < 1 || measureNumber > totalMeasures) {
            return { error: "Measure " + measureNumber + " out of range (1-" + totalMeasures + ")" };
        }

        cursorMeasure = measureNumber;
        cursorTick = -1;
        return { result: { measure: cursorMeasure, staff: cursorStaff } };
    }

    /// Move the logical cursor to the specified 0-indexed staff.
    function handleGoToStaff(params) {
        var scoreErr = requireScore();
        if (scoreErr) return scoreErr;

        if (params.staff === undefined) {
            return { error: "Missing required parameter: staff" };
        }

        var staffIndex = safeParseInt(params.staff);
        if (staffIndex === null) {
            return { error: "Invalid value for staff: " + params.staff };
        }
        if (staffIndex < 0 || staffIndex >= curScore.nstaves) {
            return { error: "Staff " + staffIndex + " out of range (0-" + (curScore.nstaves - 1) + ")" };
        }

        cursorStaff = staffIndex;
        cursorTick = -1;
        return { result: { measure: cursorMeasure, staff: cursorStaff } };
    }

    // ===================================================================
    // Command handlers -- score modification
    // ===================================================================

    /// Add a note at the current cursor position.
    /// Params: { pitch, duration?: { numerator, denominator }, advanceCursorAfterAction?: bool }
    function handleAddNote(params) {
        var req = requireCursor();
        if (req.error) return req.error;
        var cursor = req.cursor;

        if (params.pitch === undefined) {
            return { error: "Missing required parameter: pitch" };
        }

        var pitch = safeParseInt(params.pitch);
        if (pitch === null) {
            return { error: "Invalid value for pitch: " + params.pitch };
        }
        if (pitch < 0 || pitch > 127) {
            return { error: "pitch must be a MIDI value 0-127, got: " + pitch };
        }
        var numerator = 1;
        var denominator = 4;
        if (params.duration) {
            if (params.duration.numerator !== undefined) {
                numerator = safeParseInt(params.duration.numerator);
                if (numerator === null || numerator < 1)
                    return { error: "Invalid duration numerator" };
            }
            if (params.duration.denominator !== undefined) {
                denominator = safeParseInt(params.duration.denominator);
                if (denominator === null || denominator < 1)
                    return { error: "Invalid duration denominator" };
            }
        }
        var advance = (params.advanceCursorAfterAction !== false);

        // try/finally: never leave an open command group if addNote throws.
        curScore.startCmd("addNote");
        try {
            cursor.setDuration(numerator, denominator);
            cursor.addNote(pitch);
        } finally {
            curScore.endCmd();
        }

        if (advance) {
            cursorMeasure = measureNumberAtTick(cursor.tick);
            cursorTick = cursor.tick;
        }

        return {
            result: {
                pitch: pitch,
                duration: { numerator: numerator, denominator: denominator },
                measure: cursorMeasure,
                staff: cursorStaff
            }
        };
    }

    /// Add a rehearsal mark at the current cursor position.
    /// Params: { text }
    function handleAddRehearsalMark(params) {
        var req = requireCursor();
        if (req.error) return req.error;
        var cursor = req.cursor;

        if (params.text === undefined || params.text === "") {
            return { error: "Missing required parameter: text" };
        }

        if (!cursor.segment) {
            return { error: "No valid segment at cursor position" };
        }

        curScore.startCmd("addRehearsalMark");
        try {
            var rehearsalMark = newElement(Element.REHEARSAL_MARK);
            rehearsalMark.text = params.text;
            cursor.add(rehearsalMark);
        } finally {
            curScore.endCmd();
        }

        return { result: { text: params.text, measure: cursorMeasure } };
    }

    /// Set the barline type at the current cursor position.
    /// Params: { type }
    function handleSetBarline(params) {
        var req = requireCursor();
        if (req.error) return req.error;
        var cursor = req.cursor;

        if (params.type === undefined) {
            return { error: "Missing required parameter: type" };
        }

        var barlineType = barlineTypeFromString(params.type);
        if (barlineType === null) {
            return { error: "Unknown barline type: " + params.type +
                ". Valid types: " + Object.keys(barlineTypes).join(", ") };
        }

        if (!cursor.measure) {
            return { error: "No valid measure at cursor position" };
        }

        if (params.__experimental !== true) {
            return { error: "setBarline is disabled: it crashes MuseScore " +
                "Studio 4.7.4 outright (newElement + cursor.add is fatal " +
                "for BAR_LINE). Pass __experimental: true to probe at " +
                "your own risk." };
        }

        curScore.startCmd("setBarline");
        try {
            var barline = newElement(Element.BAR_LINE);
            barline.barlineType = barlineType;
            cursor.add(barline);
        } finally {
            curScore.endCmd();
        }

        return { result: { type: params.type, measure: cursorMeasure } };
    }

    /// Set the key signature at the current cursor position.
    /// Params: { fifths } (-7 to 7 on the circle of fifths)
    function handleSetKeySignature(params) {
        var req = requireCursor();
        if (req.error) return req.error;
        var cursor = req.cursor;

        if (params.fifths === undefined) {
            return { error: "Missing required parameter: fifths" };
        }

        var fifths = safeParseInt(params.fifths);
        if (fifths === null) {
            return { error: "Invalid value for fifths: " + params.fifths };
        }
        if (fifths < minFifths || fifths > maxFifths) {
            return { error: "fifths must be between " + minFifths + " and " + maxFifths + ", got: " + fifths };
        }
        if (!cursor.segment) {
            return { error: "No valid segment at cursor position" };
        }

        var postAddKey = null;
        curScore.startCmd("setKeySignature");
        try {
            var keySig = newElement(Element.KEYSIG);
            keySig.key = fifths;
            cursor.add(keySig);
            // cursor.add may clone or reset the element in MuseScore 4
            // (inserted key signatures export as -8 regardless of the
            // value written before add); re-assign after insertion.
            keySig.key = fifths;
            postAddKey = keySig.key;
        } finally {
            curScore.endCmd();
        }

        return {
            result: {
                fifths: fifths,
                measure: cursorMeasure,
                postAddKey: postAddKey
            }
        };
    }

    /// Set the time signature at the current cursor position.
    /// Params: { numerator, denominator }
    function handleSetTimeSignature(params) {
        var req = requireCursor();
        if (req.error) return req.error;
        var cursor = req.cursor;

        if (params.numerator === undefined || params.denominator === undefined) {
            return { error: "Missing required parameters: numerator and denominator" };
        }

        var numerator = safeParseInt(params.numerator);
        var denominator = safeParseInt(params.denominator);
        if (numerator === null || denominator === null) {
            return { error: "Invalid time signature values" };
        }
        if (!cursor.segment) {
            return { error: "No valid segment at cursor position" };
        }

        curScore.startCmd("setTimeSignature");
        try {
            var timeSig = newElement(Element.TIMESIG);
            timeSig.timesig = fraction(numerator, denominator);
            cursor.add(timeSig);
        } finally {
            curScore.endCmd();
        }

        return { result: { numerator: numerator, denominator: denominator, measure: cursorMeasure } };
    }

    /// Set a tempo marking at the current cursor position.
    /// Params: { bpm, text? }
    function handleSetTempo(params) {
        var req = requireCursor();
        if (req.error) return req.error;
        var cursor = req.cursor;

        if (params.bpm === undefined) {
            return { error: "Missing required parameter: bpm" };
        }

        var bpm = safeParseInt(params.bpm);
        if (bpm === null) {
            return { error: "Invalid value for bpm: " + params.bpm };
        }
        var displayText = params.text || ("\u2669 = " + bpm);

        if (!cursor.segment) {
            return { error: "No valid segment at cursor position" };
        }

        var postAdd = null;
        curScore.startCmd("setTempo");
        try {
            var tempo = newElement(Element.TEMPO_TEXT);
            tempo.text = displayText;
            tempo.tempo = bpm / secondsPerMinute;
            tempo.followText = false;
            cursor.add(tempo);
            // Re-assign after insertion: inserted TEMPO_TEXT exports with
            // empty text/tempo when only set before cursor.add.
            tempo.text = displayText;
            tempo.tempo = bpm / secondsPerMinute;
            tempo.followText = false;
            postAdd = { text: tempo.text, tempo: tempo.tempo };
        } finally {
            curScore.endCmd();
        }

        return {
            result: {
                bpm: bpm,
                text: displayText,
                measure: cursorMeasure,
                postAdd: postAdd
            }
        };
    }

    /// Add a chord symbol at the current cursor position.
    /// Params: { text }
    function handleAddChordSymbol(params) {
        var req = requireCursor();
        if (req.error) return req.error;
        var cursor = req.cursor;

        if (params.text === undefined || params.text === "") {
            return { error: "Missing required parameter: text" };
        }

        if (!cursor.segment) {
            return { error: "No valid segment at cursor position" };
        }

        if (params.__experimental !== true) {
            return { error: "addChordSymbol is disabled: it crashes " +
                "MuseScore Studio 4.7.4 outright (newElement + cursor.add " +
                "is fatal for HARMONY). Pass __experimental: true to probe " +
                "at your own risk." };
        }

        curScore.startCmd("addChordSymbol");
        try {
            var harmony = newElement(Element.HARMONY);
            harmony.text = params.text;
            cursor.add(harmony);
        } finally {
            curScore.endCmd();
        }

        return { result: { text: params.text, measure: cursorMeasure } };
    }

    /// Add a dynamic marking at the current cursor position.
    /// Params: { type }
    function handleAddDynamic(params) {
        var req = requireCursor();
        if (req.error) return req.error;
        var cursor = req.cursor;

        if (params.type === undefined || params.type === "") {
            return { error: "Missing required parameter: type" };
        }

        if (!cursor.segment) {
            return { error: "No valid segment at cursor position" };
        }

        if (params.__experimental !== true) {
            return { error: "addDynamic is disabled: newElement + " +
                "cursor.add crashes MuseScore Studio 4.7.4 for the same " +
                "element family as setBarline/addChordSymbol. Pass " +
                "__experimental: true to probe at your own risk." };
        }

        curScore.startCmd("addDynamic");
        try {
            var dynamic = newElement(Element.DYNAMIC);
            dynamic.text = params.type;
            if (dynamicVelocities[params.type] !== undefined) {
                dynamic.velocity = dynamicVelocities[params.type];
            }
            cursor.add(dynamic);
        } finally {
            curScore.endCmd();
        }

        return { result: { type: params.type, measure: cursorMeasure } };
    }

    /// Append empty measures to the end of the score.
    /// Params: { count }
    function handleAppendMeasures(params) {
        var scoreErr = requireScore();
        if (scoreErr) return scoreErr;

        if (params.count === undefined) {
            return { error: "Missing required parameter: count" };
        }

        var count = safeParseInt(params.count);
        if (count === null || count < 1) {
            return { error: "count must be at least 1, got: " + count };
        }

        curScore.startCmd("appendMeasures");
        try {
            curScore.appendMeasures(count);
        } finally {
            curScore.endCmd();
        }

        return { result: { count: count, totalMeasures: countMeasures() } };
    }

    // ===================================================================
    // Command handlers -- selection and transposition
    // ===================================================================

    /// Select all elements in the measure at the current cursor position.
    function handleSelectCurrentMeasure() {
        var req = requireCursor();
        if (req.error) return req.error;
        var cursor = req.cursor;

        if (!cursor.measure) {
            return { error: "No measure at current cursor position" };
        }

        var measureStart = cursor.measure.firstSegment.tick;
        var measureEnd = cursor.measure.lastSegment.tick + 1;

        // A selection is not an edit: no startCmd/endCmd. Wrapping it in a
        // command group pollutes the undo stack with empty entries.
        curScore.selection.selectRange(
            measureStart, measureEnd,
            cursorStaff, cursorStaff + 1
        );

        return { result: { measure: cursorMeasure, staff: cursorStaff } };
    }

    /// Select a range of measures and staves.
    /// Params: { startMeasure, endMeasure, startStaff, endStaff }
    /// Measures are 1-indexed (inclusive). Staves are 0-indexed (inclusive).
    function handleSelectCustomRange(params) {
        var scoreErr = requireScore();
        if (scoreErr) return scoreErr;

        var startMeasure = parseInt(params.startMeasure);
        var endMeasure = parseInt(params.endMeasure);
        var startStaff = parseInt(params.startStaff);
        var endStaff = parseInt(params.endStaff);

        if (isNaN(startMeasure) || isNaN(endMeasure) ||
            isNaN(startStaff) || isNaN(endStaff)) {
            return { error: "Missing required parameters: startMeasure, endMeasure, startStaff, endStaff" };
        }

        var totalMeasures = countMeasures();
        if (startMeasure < 1 || startMeasure > totalMeasures ||
            endMeasure < 1 || endMeasure > totalMeasures ||
            startMeasure > endMeasure) {
            return { error: "Invalid measure range: " + startMeasure + "-" + endMeasure +
                " (score has " + totalMeasures + " measures)" };
        }
        if (startStaff < 0 || startStaff >= curScore.nstaves ||
            endStaff < 0 || endStaff >= curScore.nstaves ||
            startStaff > endStaff) {
            return { error: "Invalid staff range: " + startStaff + "-" + endStaff +
                " (score has " + curScore.nstaves + " staves)" };
        }

        // Find tick positions for the measure range.
        var cursor = curScore.newCursor();
        advanceCursorToMeasure(cursor, startMeasure);
        var startTick = cursor.tick;

        for (var j = startMeasure; j <= endMeasure; j++) {
            cursor.nextMeasure();
        }
        var endTick = cursor.measure ? cursor.tick : curScore.lastSegment.tick + 1;

        // A selection is not an edit: no startCmd/endCmd (undo hygiene).
        curScore.selection.selectRange(
            startTick, endTick,
            startStaff, endStaff + 1  // selectRange uses exclusive end for staves
        );

        return {
            result: {
                startMeasure: startMeasure,
                endMeasure: endMeasure,
                startStaff: startStaff,
                endStaff: endStaff
            }
        };
    }

    /// Transpose notes by a number of semitones.
    /// Params: { semitones, startMeasure?, endMeasure?, startStaff?, endStaff? }
    /// With range parameters the range is walked directly (reliable).
    /// Without them the current selection is used -- but selectRange does
    /// not produce an active selection in MuseScore 4, so the ranged form
    /// is the only dependable path.
    function handleTranspose(params) {
        var scoreErr = requireScore();
        if (scoreErr) return scoreErr;

        if (params.semitones === undefined) {
            return { error: "Missing required parameter: semitones" };
        }

        var semitones = safeParseInt(params.semitones);
        if (semitones === null) {
            return { error: "Invalid value for semitones: " + params.semitones };
        }

        // curScore.transpose() does not exist in MuseScore 4's plugin API,
        // so transpose note-by-note: shift pitch and adjust the tonal pitch
        // class (tpc) so the enharmonic spelling stays correct.

        if (params.startMeasure !== undefined) {
            return transposeRange(params, semitones);
        }

        if (!curScore.selection || !curScore.selection.elements ||
            curScore.selection.elements.length === 0) {
            return { error: "No active selection. Use selectCurrentMeasure or selectCustomRange first." };
        }

        var transposed = 0;
        curScore.startCmd("transpose");
        try {
            var elements = curScore.selection.elements;
            for (var i = 0; i < elements.length; i++) {
                var element = elements[i];
                if (element.type === Element.NOTE) {
                    transposeNote(element, semitones);
                    transposed++;
                } else if (element.type === Element.CHORD && element.notes) {
                    for (var j = 0; j < element.notes.length; j++) {
                        transposeNote(element.notes[j], semitones);
                        transposed++;
                    }
                }
            }
        } finally {
            curScore.endCmd();
        }

        return { result: { semitones: semitones, notesTransposed: transposed } };
    }

    /// Transpose every note in an inclusive measure/staff range by
    /// walking a cursor over each staff -- no selection required.
    function transposeRange(params, semitones) {
        var startMeasure = safeParseInt(params.startMeasure);
        var endMeasure = safeParseInt(
            params.endMeasure !== undefined ? params.endMeasure : params.startMeasure);
        var startStaff = safeParseInt(
            params.startStaff !== undefined ? params.startStaff : 0);
        var endStaff = safeParseInt(
            params.endStaff !== undefined ? params.endStaff : startStaff);

        if (startMeasure === null || endMeasure === null ||
            startStaff === null || endStaff === null) {
            return { error: "Invalid range parameters" };
        }
        var totalMeasures = countMeasures();
        if (startMeasure < 1 || endMeasure > totalMeasures ||
            startMeasure > endMeasure) {
            return { error: "Invalid measure range: " + startMeasure + "-" +
                endMeasure + " (score has " + totalMeasures + " measures)" };
        }
        if (startStaff < 0 || endStaff >= curScore.nstaves ||
            startStaff > endStaff) {
            return { error: "Invalid staff range: " + startStaff + "-" +
                endStaff + " (score has " + curScore.nstaves + " staves)" };
        }

        var transposed = 0;
        curScore.startCmd("transpose");
        try {
            for (var staff = startStaff; staff <= endStaff; staff++) {
                var cursor = curScore.newCursor();
                cursor.staffIdx = staff;
                cursor.voice = 0;
                cursor.rewind(Cursor.SCORE_START);
                for (var i = 1; i < startMeasure; i++) {
                    cursor.nextMeasure();
                }
                while (cursor.segment &&
                       measureNumberAtTick(cursor.tick) <= endMeasure) {
                    var element = cursor.element;
                    if (element && element.type === Element.CHORD && element.notes) {
                        for (var j = 0; j < element.notes.length; j++) {
                            transposeNote(element.notes[j], semitones);
                            transposed++;
                        }
                    }
                    if (!cursor.next()) break;
                }
            }
        } finally {
            curScore.endCmd();
        }

        return {
            result: {
                semitones: semitones,
                startMeasure: startMeasure,
                endMeasure: endMeasure,
                startStaff: startStaff,
                endStaff: endStaff,
                notesTransposed: transposed
            }
        };
    }

    // Tonal-pitch-class delta per semitone step, chosen for conventional
    // chromatic spelling (e.g. +1 from C gives C#, -1 from C gives B).
    // tpc moves in fifths: +7 = augmented unison (sharpen), -5 = minor
    // second, etc. Index = ((semitones % 12) + 12) % 12.
    readonly property var semitoneToTpcDelta: [0, 7, 2, -3, 4, -1, 6, 1, -4, 3, -2, 5]

    /// Transpose one note by the given number of semitones, keeping a
    /// sensible enharmonic spelling and clamping tpc into MuseScore's
    /// valid range (-1..33) by respelling when necessary.
    function transposeNote(note, semitones) {
        var tpcDelta = semitoneToTpcDelta[((semitones % 12) + 12) % 12];
        var newTpc = note.tpc + tpcDelta;
        // Respell out-of-range spellings enharmonically (12 fifths = same
        // pitch class, opposite accidental family).
        while (newTpc > 33) newTpc -= 12;
        while (newTpc < -1) newTpc += 12;
        note.pitch = note.pitch + semitones;
        note.tpc = newTpc;
    }

    /// Undo the last action.
    function handleUndo() {
        var scoreErr = requireScore();
        if (scoreErr) return scoreErr;

        cmd("undo");

        // Clamp cursor to valid bounds — undo may have changed the score
        // structure (removed measures, changed staves).
        var totalMeasures = countMeasures();
        if (totalMeasures > 0 && cursorMeasure > totalMeasures) {
            cursorMeasure = totalMeasures;
        }
        if (curScore.nstaves > 0 && cursorStaff >= curScore.nstaves) {
            cursorStaff = curScore.nstaves - 1;
        }
        cursorTick = -1;

        return { result: "ok" };
    }

    // ===================================================================
    // Command handler -- processSequence (atomic batch execution)
    // ===================================================================

    /// Execute multiple actions atomically in a single undo group.
    /// If any action fails, all preceding actions are rolled back.
    ///
    /// Params: { sequence: [{ action, params }, ...] }
    function handleProcessSequence(params) {
        var scoreErr = requireScore();
        if (scoreErr) return scoreErr;

        if (!params.sequence || !Array.isArray(params.sequence)) {
            return { error: "Missing required parameter: sequence (array of {action, params})" };
        }

        var sequence = params.sequence;
        if (sequence.length === 0) {
            return { result: { results: [], count: 0 } };
        }

        var results = [];

        // Single startCmd/endCmd wraps all steps into one undo group.
        curScore.startCmd("processSequence");

        // Shared cursor threaded across steps so consecutive addNote calls
        // advance forward instead of each rewinding to the measure start.
        var seqCursor = positionedCursor();

        for (var i = 0; i < sequence.length; i++) {
            var step = sequence[i];
            var action = step.action;
            var actionParams = step.params || {};

            if (!action) {
                curScore.endCmd();
                cmd("undo");
                return {
                    error: "Step " + i + " is missing 'action' field",
                    failedIndex: i,
                    results: results
                };
            }

            var stepResult;
            try {
                stepResult = executeSequenceStep(action, actionParams, seqCursor);
                if (stepResult.newCursor) {
                    seqCursor = stepResult.newCursor;
                    delete stepResult.newCursor;
                }
            } catch (e) {
                curScore.endCmd();
                cmd("undo");
                return {
                    error: "Step " + i + " (" + action + ") failed: " + (e.message || String(e)),
                    failedAction: action,
                    failedIndex: i,
                    results: results
                };
            }

            if (stepResult.error) {
                curScore.endCmd();
                cmd("undo");
                return {
                    error: "Step " + i + " (" + action + ") failed: " + stepResult.error,
                    failedAction: action,
                    failedIndex: i,
                    results: results
                };
            }

            results.push(stepResult.result);
        }

        curScore.endCmd();

        return { result: { results: results, count: results.length } };
    }

    /// Execute a single step within processSequence WITHOUT its own
    /// startCmd/endCmd (the caller manages the undo group).
    function executeSequenceStep(action, params, cursor) {
        switch (action) {
            case "ping":
                return { result: "pong" };

            case "goToMeasure": {
                if (params.measure === undefined)
                    return { error: "Missing required parameter: measure" };
                var measureNum = safeParseInt(params.measure);
                if (measureNum === null)
                    return { error: "Invalid value for measure: " + params.measure };
                var total = countMeasures();
                if (measureNum < 1 || measureNum > total)
                    return { error: "Measure " + measureNum + " out of range (1-" + total + ")" };
                cursorMeasure = measureNum;
                cursorTick = -1;
                return { result: { measure: cursorMeasure, staff: cursorStaff }, newCursor: positionedCursor() };
            }

            case "goToStaff": {
                if (params.staff === undefined)
                    return { error: "Missing required parameter: staff" };
                var staffIdx = safeParseInt(params.staff);
                if (staffIdx === null)
                    return { error: "Invalid value for staff: " + params.staff };
                if (staffIdx < 0 || staffIdx >= curScore.nstaves)
                    return { error: "Staff " + staffIdx + " out of range (0-" + (curScore.nstaves - 1) + ")" };
                cursorStaff = staffIdx;
                cursorTick = -1;
                return { result: { measure: cursorMeasure, staff: cursorStaff }, newCursor: positionedCursor() };
            }

            case "addNote": {
                if (params.pitch === undefined)
                    return { error: "Missing required parameter: pitch" };
                var pitch = safeParseInt(params.pitch);
                if (pitch === null)
                    return { error: "Invalid value for pitch: " + params.pitch };
                var noteNum = 1;
                var noteDen = 4;
                if (params.duration) {
                    if (params.duration.numerator !== undefined) {
                        noteNum = safeParseInt(params.duration.numerator);
                        if (noteNum === null) return { error: "Invalid duration numerator" };
                    }
                    if (params.duration.denominator !== undefined) {
                        noteDen = safeParseInt(params.duration.denominator);
                        if (noteDen === null) return { error: "Invalid duration denominator" };
                    }
                }
                if (pitch < 0 || pitch > 127) {
                    return { error: "pitch must be a MIDI value 0-127, got: " + pitch };
                }
                var advance = (params.advanceCursorAfterAction !== false);
                if (!cursor) return { error: "Could not position cursor" };
                cursor.setDuration(noteNum, noteDen);
                cursor.addNote(pitch);
                if (advance) {
                    cursorMeasure = measureNumberAtTick(cursor.tick);
                    cursorTick = cursor.tick;
                }
                return { result: { pitch: pitch, duration: { numerator: noteNum, denominator: noteDen }, measure: cursorMeasure } };
            }

            case "addRehearsalMark": {
                if (!params.text)
                    return { error: "Missing required parameter: text" };
                var rmCursor = positionedCursor();
                if (!rmCursor) return { error: "Could not position cursor" };
                if (!rmCursor.segment) return { error: "No valid segment at cursor position" };
                var rehearsalMark = newElement(Element.REHEARSAL_MARK);
                rehearsalMark.text = params.text;
                rmCursor.add(rehearsalMark);
                return { result: { text: params.text, measure: cursorMeasure } };
            }

            case "setBarline": {
                if (!params.type)
                    return { error: "Missing required parameter: type" };
                var barlineValue = barlineTypeFromString(params.type);
                if (barlineValue === null)
                    return { error: "Unknown barline type: " + params.type };
                var blCursor = positionedCursor();
                if (!blCursor) return { error: "Could not position cursor" };
                if (!blCursor.measure) return { error: "No valid measure at cursor position" };
                var barline = newElement(Element.BAR_LINE);
                barline.barlineType = barlineValue;
                blCursor.add(barline);
                return { result: { type: params.type, measure: cursorMeasure } };
            }

            case "setKeySignature": {
                if (params.fifths === undefined)
                    return { error: "Missing required parameter: fifths" };
                var fifths = safeParseInt(params.fifths);
                if (fifths === null)
                    return { error: "Invalid value for fifths: " + params.fifths };
                if (fifths < minFifths || fifths > maxFifths)
                    return { error: "fifths must be between " + minFifths + " and " + maxFifths };
                var ksCursor = positionedCursor();
                if (!ksCursor) return { error: "Could not position cursor" };
                if (!ksCursor.segment) return { error: "No valid segment at cursor position" };
                var keySig = newElement(Element.KEYSIG);
                keySig.key = fifths;
                ksCursor.add(keySig);
                return { result: { fifths: fifths, measure: cursorMeasure } };
            }

            case "setTimeSignature": {
                if (params.numerator === undefined || params.denominator === undefined)
                    return { error: "Missing required parameters: numerator and denominator" };
                var tsNum = safeParseInt(params.numerator);
                var tsDen = safeParseInt(params.denominator);
                if (tsNum === null || tsDen === null)
                    return { error: "Invalid time signature values" };
                var tsCursor = positionedCursor();
                if (!tsCursor) return { error: "Could not position cursor" };
                if (!tsCursor.segment) return { error: "No valid segment at cursor position" };
                var timeSig = newElement(Element.TIMESIG);
                timeSig.timesig = fraction(tsNum, tsDen);
                tsCursor.add(timeSig);
                return { result: { numerator: tsNum, denominator: tsDen, measure: cursorMeasure } };
            }

            case "setTempo": {
                if (params.bpm === undefined)
                    return { error: "Missing required parameter: bpm" };
                var bpm = safeParseInt(params.bpm);
                if (bpm === null)
                    return { error: "Invalid value for bpm: " + params.bpm };
                var tempoText = params.text || ("\u2669 = " + bpm);
                var tempoCursor = positionedCursor();
                if (!tempoCursor) return { error: "Could not position cursor" };
                if (!tempoCursor.segment) return { error: "No valid segment at cursor position" };
                var tempoMark = newElement(Element.TEMPO_TEXT);
                tempoMark.text = tempoText;
                tempoMark.tempo = bpm / secondsPerMinute;
                tempoMark.followText = false;
                tempoCursor.add(tempoMark);
                return { result: { bpm: bpm, text: tempoText, measure: cursorMeasure } };
            }

            case "addChordSymbol": {
                if (!params.text)
                    return { error: "Missing required parameter: text" };
                var chordCursor = positionedCursor();
                if (!chordCursor) return { error: "Could not position cursor" };
                if (!chordCursor.segment) return { error: "No valid segment at cursor position" };
                var harmony = newElement(Element.HARMONY);
                harmony.text = params.text;
                chordCursor.add(harmony);
                return { result: { text: params.text, measure: cursorMeasure } };
            }

            case "addDynamic": {
                if (!params.type)
                    return { error: "Missing required parameter: type" };
                var dynCursor = positionedCursor();
                if (!dynCursor) return { error: "Could not position cursor" };
                if (!dynCursor.segment) return { error: "No valid segment at cursor position" };
                var dynamic = newElement(Element.DYNAMIC);
                dynamic.text = params.type;
                if (dynamicVelocities[params.type] !== undefined) {
                    dynamic.velocity = dynamicVelocities[params.type];
                }
                dynCursor.add(dynamic);
                return { result: { type: params.type, measure: cursorMeasure } };
            }

            case "appendMeasures": {
                if (params.count === undefined)
                    return { error: "Missing required parameter: count" };
                var appendCount = safeParseInt(params.count);
                if (appendCount === null || appendCount < 1)
                    return { error: "count must be at least 1" };
                curScore.appendMeasures(appendCount);
                return { result: { count: appendCount, totalMeasures: countMeasures() } };
            }

            case "selectCurrentMeasure": {
                var selCursor = positionedCursor();
                if (!selCursor) return { error: "Could not position cursor" };
                if (!selCursor.measure) return { error: "No measure at current cursor position" };
                var selStart = selCursor.measure.firstSegment.tick;
                var selEnd = selCursor.measure.lastSegment.tick + 1;
                curScore.selection.selectRange(selStart, selEnd, cursorStaff, cursorStaff + 1);
                return { result: { measure: cursorMeasure, staff: cursorStaff } };
            }

            case "selectCustomRange": {
                var srStartMeasure = safeParseInt(params.startMeasure);
                var srEndMeasure = safeParseInt(params.endMeasure);
                var srStartStaff = safeParseInt(params.startStaff);
                var srEndStaff = safeParseInt(params.endStaff);
                if (srStartMeasure === null || srEndMeasure === null ||
                    srStartStaff === null || srEndStaff === null)
                    return { error: "Missing required parameters: startMeasure, endMeasure, startStaff, endStaff" };
                var srTotal = countMeasures();
                if (srStartMeasure < 1 || srStartMeasure > srTotal ||
                    srEndMeasure < 1 || srEndMeasure > srTotal ||
                    srStartMeasure > srEndMeasure)
                    return { error: "Invalid measure range: " + srStartMeasure + "-" + srEndMeasure };
                if (srStartStaff < 0 || srStartStaff >= curScore.nstaves ||
                    srEndStaff < 0 || srEndStaff >= curScore.nstaves ||
                    srStartStaff > srEndStaff)
                    return { error: "Invalid staff range: " + srStartStaff + "-" + srEndStaff };
                var srCursor = curScore.newCursor();
                advanceCursorToMeasure(srCursor, srStartMeasure);
                var srStartTick = srCursor.tick;
                for (var k = srStartMeasure; k <= srEndMeasure; k++) {
                    srCursor.nextMeasure();
                }
                var srEndTick = srCursor.measure ? srCursor.tick : curScore.lastSegment.tick + 1;
                curScore.selection.selectRange(srStartTick, srEndTick, srStartStaff, srEndStaff + 1);
                return { result: { startMeasure: srStartMeasure, endMeasure: srEndMeasure, startStaff: srStartStaff, endStaff: srEndStaff } };
            }

            case "transpose": {
                if (params.semitones === undefined)
                    return { error: "Missing required parameter: semitones" };
                var trSemitones = safeParseInt(params.semitones);
                if (trSemitones === null)
                    return { error: "Invalid value for semitones: " + params.semitones };
                if (!curScore.selection || !curScore.selection.elements ||
                    curScore.selection.elements.length === 0)
                    return { error: "No active selection. Use selectCurrentMeasure or selectCustomRange first." };
                var trDirection = trSemitones >= 0 ? 0 : 1;
                var trAbs = Math.abs(trSemitones);
                var trDiatonic = semitoneToDiatonic[trAbs % 12] + Math.floor(trAbs / 12) * 7;
                curScore.transpose(0, trDirection, 0, trDiatonic, trAbs, true, true);
                return { result: { semitones: trSemitones } };
            }

            default:
                return { error: "Unknown action in sequence: " + action };
        }
    }

    // ===================================================================
    // Plugin lifecycle
    // ===================================================================

    onRun: {
        console.log(logPrefix, "Bridge plugin started -- WebSocket server on port", serverPort);
        api.websocketserver.listen(serverPort, function(clientId) {
            console.log(logPrefix, "Client connected, id:", clientId);
            api.websocketserver.onMessage(clientId, function(message) {
                var response = handleMessage(message);
                api.websocketserver.send(clientId, JSON.stringify(response));
            });
        });
    }

    // Minimal invisible UI (required for dock plugin type to keep running).
    Rectangle {
        visible: false
        width: 0
        height: 0
    }
}
