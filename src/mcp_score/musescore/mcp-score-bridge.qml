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
//   processSequence, exportScore, newScore, apiProbe,
//   getClefs, setClef, removeClef
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
    version: "0.4.5"

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

    // Clef name -> MuseScore ClefType enum value (libmscore/clef.h).
    //
    // These integers are NOT stable across MuseScore versions: C-clef
    // variants between C5 and F have been added over time, which shifts
    // every value from F onwards. Verified against MuseScore Studio 4.7.4
    // by writing each clef and reading the exported MusicXML sign back
    // (tests/live/test_clefs.py). An earlier table taken from the enum
    // declaration had every value from F onwards one too high, which
    // silently wrote the wrong clef -- do not "correct" these from source
    // without re-running that test. Callers needing a variant not listed
    // here pass an explicit `subtype` integer instead.
    readonly property var clefTypes: ({
        "treble":     0,   // G
        "treble8vb":  2,   // G8_VB (tenor voice, guitar)
        "treble8va":  3,   // G8_VA
        "alto":       10,  // C3
        "tenor":      11,  // C4
        "bass":       20,  // F
        "bass8vb":    22,  // F8_VB
        "percussion": 29   // PERC
    })

    // ===================================================================
    // Internal cursor state
    // ===================================================================

    // Logical cursor position, maintained across commands. The MuseScore
    // Cursor object is re-created from this state for each command.

    property int cursorMeasure: 1   // 1-indexed measure number
    property int cursorStaff: 0     // 0-indexed staff index
    property int cursorVoice: 0     // 0-indexed voice (0-3), set by goToStaff
    property int cursorTick: -1     // intra-measure tick (-1 = measure start);
                                    // advanced by addNote so consecutive notes
                                    // accumulate instead of overwriting
    property int lastWriteTick: -1  // tick of the chord most recently written
                                    // by addNote; addToChord stacks onto it

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
                case "addRest":             return handleAddRest(params);
                case "setPitches":          return handleSetPitches(params);
                case "addRehearsalMark":    return handleAddRehearsalMark(params);
                case "setBarline":          return handleSetBarline(params);
                case "setKeySignature":     return handleSetKeySignature(params);
                case "setTimeSignature":    return handleSetTimeSignature(params);
                case "getClefs":            return handleGetClefs(params);
                case "setClef":             return handleSetClef(params);
                case "removeClef":          return handleRemoveClef(params);
                case "setTempo":            return handleSetTempo(params);
                case "addChordSymbol":      return handleAddChordSymbol(params);
                case "addDynamic":          return handleAddDynamic(params);
                case "appendMeasures":      return handleAppendMeasures(params);
                case "selectCurrentMeasure": return handleSelectCurrentMeasure();
                case "selectCustomRange":   return handleSelectCustomRange(params);
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
    ///
    /// Voices 1-3 are usually empty, and an empty voice cannot be walked
    /// (rewind/nextMeasure only stop at segments holding an element for
    /// that track). The target tick is therefore always computed in
    /// voice 0, which MuseScore keeps filled with rests, and the cursor
    /// is then placed on that tick in the requested voice.
    function positionedCursor() {
        if (!curScore) return null;
        var cursor = curScore.newCursor();
        cursor.staffIdx = cursorStaff;
        cursor.voice = 0;
        cursor.rewind(Cursor.SCORE_START);

        for (var i = 1; i < cursorMeasure; i++) {
            cursor.nextMeasure();
        }
        if (cursorTick >= 0) {
            while (cursor.tick < cursorTick && cursor.next()) {
                // seek forward within the score to the recorded tick
            }
        }
        if (cursorVoice === 0) return cursor;
        return cursorAtTick(cursorStaff, cursorVoice, cursor.tick);
    }

    /// Walk a cursor forward to an absolute tick (voice 0 only).
    function seekTick(cursor, tick) {
        cursor.rewind(Cursor.SCORE_START);
        while (cursor.segment && cursor.tick < tick) {
            if (!cursor.next()) break;
        }
        return cursor;
    }

    /// Cursor-positioning strategies for a staff+voice+tick.
    ///
    /// MuseScore's cursor navigation only stops at segments that hold an
    /// element for the cursor's *track*, so voices 1-3 -- normally empty
    /// -- cannot be reached by rewind, nextMeasure, or rewindToTick.
    /// ChordRest segments are shared by all four voices of a measure,
    /// though, so the workable route is to find the segment in voice 0
    /// (which MuseScore keeps filled with rests) and only then switch
    /// the cursor's voice or track.
    ///
    /// Builds differ in which of these MuseScore accepts, so all are
    /// tried and the first that actually lands on the tick wins.
    function cursorStrategies(staffIdx, voice, tick) {
        return [
            // Position in voice 0, then switch voice on the same segment.
            function () {
                var c = curScore.newCursor();
                c.staffIdx = staffIdx;
                c.voice = 0;
                seekTick(c, tick);
                c.voice = voice;
                return c;
            },
            // Same, but through the combined track index (staff * 4 + voice).
            function () {
                var c = curScore.newCursor();
                c.staffIdx = staffIdx;
                c.voice = 0;
                seekTick(c, tick);
                c.track = staffIdx * 4 + voice;
                return c;
            },
            // Initialize the cursor first (a fresh one points nowhere),
            // then address the segment by tick.
            function () {
                var c = curScore.newCursor();
                c.staffIdx = staffIdx;
                c.voice = voice;
                c.rewind(Cursor.SCORE_START);
                if (typeof c.rewindToTick === "function") c.rewindToTick(tick);
                return c;
            }
        ];
    }

    /// Place a cursor on an absolute tick in a given staff+voice, using
    /// the first strategy that verifiably lands there.
    function cursorAtTick(staffIdx, voice, tick) {
        if (!curScore) return null;
        var strategies = cursorStrategies(staffIdx, voice, tick);
        var fallback = null;
        for (var i = 0; i < strategies.length; i++) {
            var candidate = null;
            try {
                candidate = strategies[i]();
            } catch (e) {
                candidate = null;
            }
            if (!candidate) continue;
            if (candidate.segment && candidate.tick === tick) return candidate;
            if (!fallback) fallback = candidate;
        }
        return fallback;
    }

    /// Navigate a raw cursor to a specific 1-indexed measure number.
    function advanceCursorToMeasure(cursor, measureNumber) {
        cursor.rewind(Cursor.SCORE_START);
        for (var i = 1; i < measureNumber; i++) {
            cursor.nextMeasure();
        }
    }

    /// Chord notes in ascending-pitch order.
    ///
    /// MuseScore does not guarantee the order of Chord.notes, but the
    /// server addresses notes positionally (see collectNotesInRange), so
    /// both sides must agree. Ascending MIDI pitch is the shared
    /// convention -- it matches how the MusicXML snapshot is normalized
    /// on the server (mcp_score.musicxml sorts chord pitches the same
    /// way).
    function notesByPitch(chordElement) {
        var sorted = [];
        if (!chordElement || !chordElement.notes) return sorted;
        for (var i = 0; i < chordElement.notes.length; i++) {
            sorted.push(chordElement.notes[i]);
        }
        sorted.sort(function (a, b) { return a.pitch - b.pitch; });
        return sorted;
    }

    /// Every note of one staff+voice across an inclusive measure range,
    /// in deterministic walker order: segment tick ascending, then
    /// ascending pitch within each chord.
    ///
    /// This is the addressing scheme setPitches uses. The server derives
    /// the identical ordering from its MusicXML snapshot, so edit N in
    /// the request corresponds to element N of this list.
    function collectNotesInRange(staffIdx, voice, startMeasure, endMeasure) {
        var collected = [];
        // The measure's start tick has to be found in voice 0 -- an empty
        // voice cannot be walked (see cursorStrategies).
        var probe = curScore.newCursor();
        probe.staffIdx = staffIdx;
        probe.voice = 0;
        advanceCursorToMeasure(probe, startMeasure);
        var cursor = cursorAtTick(staffIdx, voice, probe.tick);
        if (!cursor) return collected;
        while (cursor.segment &&
               measureNumberAtTick(cursor.tick) <= endMeasure) {
            var element = cursor.element;
            if (element && element.type === Element.CHORD) {
                var notes = notesByPitch(element);
                for (var i = 0; i < notes.length; i++) {
                    collected.push(notes[i]);
                }
            }
            if (!cursor.next()) break;
        }
        return collected;
    }

    /// Locate the note just written at a tick, so its spelling can be set.
    ///
    /// Returns the note with the given MIDI pitch in the chord at
    /// (staffIdx, voice, tick), or null. When a chord holds the pitch
    /// more than once the last match is returned -- that is the one a
    /// preceding addNote appended.
    function noteAtTick(staffIdx, voice, tick, pitch) {
        var cursor = curScore.newCursor();
        cursor.staffIdx = staffIdx;
        cursor.voice = voice;
        if (typeof cursor.rewindToTick === "function") {
            cursor.rewindToTick(tick);
        } else {
            cursor.rewind(Cursor.SCORE_START);
            while (cursor.segment && cursor.tick < tick) {
                if (!cursor.next()) break;
            }
        }
        if (!cursor.segment || cursor.tick !== tick) return null;
        var element = cursor.element;
        if (!element || element.type !== Element.CHORD || !element.notes) {
            return null;
        }
        for (var i = element.notes.length - 1; i >= 0; i--) {
            if (element.notes[i].pitch === pitch) return element.notes[i];
        }
        return null;
    }

    /// Apply an explicit tonal pitch class (spelling) to a note.
    ///
    /// The server computes tpc with music21, which owns every enharmonic
    /// decision; the plugin only stores it. tpc1/tpc2 are MuseScore's
    /// concert/transposed spellings -- both are set so the note reads
    /// correctly in concert-pitch and transposed views alike.
    function applyTpc(note, tpc) {
        if (!note || tpc === undefined || tpc === null) return false;
        if (tpc < -1 || tpc > 33) return false;
        note.tpc = tpc;
        if (note.tpc1 !== undefined) note.tpc1 = tpc;
        if (note.tpc2 !== undefined) note.tpc2 = tpc;
        return true;
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

    /// Measure boundaries as [{ number, startTick, endTick }], computed in
    /// one pass.
    ///
    /// measureNumberAtTick walks the score from the start on every call,
    /// so using it inside a segment walk is quadratic. Clef enumeration
    /// visits every segment in the score, hence this table.
    function measureBoundaries() {
        var bounds = [];
        if (!curScore) return bounds;
        var cursor = curScore.newCursor();
        cursor.rewind(Cursor.SCORE_START);
        var number = 1;
        while (cursor.measure) {
            var startTick = cursor.tick;
            cursor.nextMeasure();
            bounds.push({
                number: number,
                startTick: startTick,
                endTick: cursor.measure ? cursor.tick : Infinity
            });
            number++;
        }
        return bounds;
    }

    /// The 1-indexed measure number holding a tick, using a prebuilt table.
    function measureNumberFromBounds(bounds, tick) {
        for (var i = 0; i < bounds.length; i++) {
            if (tick >= bounds[i].startTick && tick < bounds[i].endTick) {
                return bounds[i].number;
            }
        }
        return bounds.length > 0 ? bounds[bounds.length - 1].number : 0;
    }

    /// Every clef in the score, in tick order.
    ///
    /// Walks raw segments rather than a Cursor: cursor.next() only stops
    /// at ChordRest segments, so it steps straight over the Clef segments
    /// this needs to find. Clefs live on the voice-0 track of their staff
    /// (track = staffIdx * 4).
    ///
    /// Each entry carries `atMeasureStart`, which is what distinguishes a
    /// normal staff-defining clef from the mid-measure clef changes
    /// MuseScore's MIDI import inserts to chase stray notes.
    /// Descriptors only -- safe to serialize into a JSON reply.
    function collectClefs(staffFilter) {
        var entries = collectClefEntries(staffFilter);
        var infos = [];
        for (var i = 0; i < entries.length; i++) infos.push(entries[i].info);
        return infos;
    }

    /// As collectClefs, but each entry keeps the live Clef element under
    /// `element` so removeClef can hand it to curScore.removeElement.
    /// Never serialize these -- QML element objects are not JSON-safe.
    function collectClefEntries(staffFilter) {
        var clefs = [];
        if (!curScore) return clefs;

        // firstSegment is a function in MuseScore 4.7.4 and a property in
        // some 3.x builds; next has the same ambiguity. Both shapes are
        // accepted so the walk does not silently traverse nothing (a
        // property read on a function object yields undefined, which is
        // how 0.4.0 first reported a piano score as having zero clefs).
        var segment = segmentValue(curScore.firstSegment, curScore);
        if (!segment) return clefs;

        var bounds = measureBoundaries();
        var staffCount = curScore.nstaves;

        while (segment) {
            for (var staffIdx = 0; staffIdx < staffCount; staffIdx++) {
                if (staffFilter !== null && staffFilter !== undefined &&
                    staffIdx !== staffFilter) {
                    continue;
                }
                var element = null;
                try {
                    element = segment.elementAt(staffIdx * 4);
                } catch (e) {
                    element = null;
                }
                if (!element || element.type !== Element.CLEF) continue;

                var measureNumber = measureNumberFromBounds(bounds, segment.tick);
                var measureStart = 0;
                for (var b = 0; b < bounds.length; b++) {
                    if (bounds[b].number === measureNumber) {
                        measureStart = bounds[b].startTick;
                        break;
                    }
                }
                // `generated` is true for anything MuseScore laid out
                // itself: the staff's opening clef and the courtesy clef
                // it repeats at every system start. `false` means a clef
                // someone inserted -- the MIDI-import leftovers included.
                var isGenerated = (element.generated === true);

                clefs.push({
                    element: element,
                    generated: isGenerated,
                    info: {
                        staff: staffIdx,
                        measure: measureNumber,
                        tick: segment.tick,
                        tickInMeasure: segment.tick - measureStart,
                        atMeasureStart: segment.tick === measureStart,
                        generated: isGenerated,
                        subtype: (element.subtype !== undefined)
                            ? element.subtype : null,
                        name: clefNameFromSubtype(element.subtype)
                    }
                });
            }
            segment = segmentValue(segment.next, segment);
        }
        return markRedundantClefs(clefs);
    }

    /// Mark clefs that restate the clef already in force on their staff.
    ///
    /// MuseScore's `generated` flag does NOT mean "courtesy clef": it is
    /// true for a staff's opening clef too, because that one is laid out
    /// from the staff's own clef property rather than authored. Treating
    /// generated as redundant therefore hides every clef in a clean score
    /// (verified: a 300-bar piano score reported zero). What it does mean
    /// is `generated: false` == inserted by someone -- which is exactly
    /// what MuseScore's MIDI import leaves mid-measure.
    ///
    /// So redundancy is derived from the reading instead: a clef whose
    /// type matches the previous clef on the same staff changes nothing.
    /// The generated flag only rescues the rare authored clef that
    /// restates the current one -- inserted deliberately, so it is kept.
    function markRedundantClefs(entries) {
        var lastSubtype = {};
        for (var i = 0; i < entries.length; i++) {
            var info = entries[i].info;
            var previous = lastSubtype[info.staff];
            var restatesCurrent =
                (previous !== undefined && previous === info.subtype);
            info.redundant = restatesCurrent && info.generated !== false;
            info.changesClef = !info.redundant;
            lastSubtype[info.staff] = info.subtype;
        }
        return entries;
    }

    /// Resolve a segment accessor that may be a property or a method.
    function segmentValue(accessor, owner) {
        if (accessor === undefined || accessor === null) return null;
        if (typeof accessor === "function") {
            try {
                return accessor.call(owner);
            } catch (e) {
                return null;
            }
        }
        return accessor;
    }

    /// Reverse-map a ClefType integer to a name from clefTypes, or null
    /// when it is a variant this plugin does not name.
    function clefNameFromSubtype(subtype) {
        if (subtype === undefined || subtype === null) return null;
        var names = Object.keys(clefTypes);
        for (var i = 0; i < names.length; i++) {
            if (clefTypes[names[i]] === subtype) return names[i];
        }
        return null;
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

    /// Describe a score element as a plain object for JSON serialization.
    ///
    /// Pitches are reported as raw (pitch, tpc) pairs. Rendering those
    /// into note names is the server's job (mcp_score.theory), which uses
    /// music21 -- the plugin deliberately holds no music theory.
    function describeElement(element) {
        if (!element) return null;

        var info = { type: element.type };

        if (element.type === Element.CHORD) {
            var notes = [];
            for (var i = 0; i < element.notes.length; i++) {
                var note = element.notes[i];
                notes.push({ pitch: note.pitch, tpc: note.tpc });
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

        // Capability probes for the 0.3.0 write-vocabulary work: do the
        // API surfaces we intend to call actually exist in this build?
        // Non-destructive -- inspects the cursor and element types without
        // touching the score.
        probe.capabilities = {};
        try {
            var capCursor = curScore ? curScore.newCursor() : null;
            probe.capabilities.cursor = {
                addNote: capCursor ? typeof capCursor.addNote : "no-score",
                addNoteArity: (capCursor && capCursor.addNote)
                    ? capCursor.addNote.length : null,
                addRest: capCursor ? typeof capCursor.addRest : "no-score",
                addRestArity: (capCursor && capCursor.addRest)
                    ? capCursor.addRest.length : null,
                setDuration: capCursor ? typeof capCursor.setDuration : "no-score"
            };
            if (capCursor) {
                // Is cursor.voice writable? Set and read back (a fresh
                // cursor, never added to the score).
                capCursor.voice = 1;
                probe.capabilities.cursor.voiceWriteBack = capCursor.voice;
            }
        } catch (e) {
            probe.capabilities.cursor = { error: e.message || String(e) };
        }
        try {
            var probeNote = newElement(Element.NOTE);
            probe.capabilities.note = {
                tieForward: typeof probeNote.tieForward,
                tieBack: typeof probeNote.tieBack,
                firstTiedNote: typeof probeNote.firstTiedNote
            };
        } catch (e) {
            probe.capabilities.note = { error: e.message || String(e) };
        }
        // Which cursor-positioning strategy actually reaches a tick in a
        // non-zero (usually empty) voice? Read-only: positions cursors
        // and reports where they landed, without writing anything.
        try {
            var probeTarget = 0;
            if (curScore) {
                var tickCursor = curScore.newCursor();
                tickCursor.staffIdx = 0;
                tickCursor.voice = 0;
                tickCursor.rewind(Cursor.SCORE_START);
                tickCursor.nextMeasure();
                probeTarget = tickCursor.tick;
            }
            var attempts = [];
            if (curScore && probeTarget > 0) {
                var probeStrategies = cursorStrategies(0, 1, probeTarget);
                for (var s = 0; s < probeStrategies.length; s++) {
                    try {
                        var pc = probeStrategies[s]();
                        attempts.push({
                            strategy: s,
                            tick: pc ? pc.tick : null,
                            hasSegment: !!(pc && pc.segment),
                            voice: pc ? pc.voice : null,
                            landed: !!(pc && pc.segment && pc.tick === probeTarget)
                        });
                    } catch (e) {
                        attempts.push({ strategy: s, error: e.message || String(e) });
                    }
                }
            }
            probe.capabilities.voicePositioning = {
                targetTick: probeTarget,
                attempts: attempts
            };
        } catch (e) {
            probe.capabilities.voicePositioning = { error: e.message || String(e) };
        }

        probe.capabilities.elementTypes = {
            REST: (typeof Element !== "undefined" && Element.REST !== undefined)
                ? Element.REST : null,
            NOTE: (typeof Element !== "undefined" && Element.NOTE !== undefined)
                ? Element.NOTE : null,
            CLEF: (typeof Element !== "undefined" && Element.CLEF !== undefined)
                ? Element.CLEF : null
        };

        // Clef support probes. ClefType integers shift between MuseScore
        // versions, so rather than trust the clefTypes table this reports
        // the subtypes of the clefs ALREADY in the score -- in a piano
        // score staff 0 is treble and staff 1 is bass, which pins the two
        // values that matter. Read-only.
        probe.capabilities.clef = {};

        // Which score-level removal API exists? 0.4.0 development found
        // curScore.removeElement undefined in 4.7.4, so every plausible
        // alternative is listed rather than assumed.
        try {
            var removalNames = ["removeElement", "deleteElement", "remove",
                "cmdRemove", "removeSelection"];
            var removal = {};
            for (var r = 0; r < removalNames.length; r++) {
                removal[removalNames[r]] =
                    curScore ? typeof curScore[removalNames[r]] : "no-score";
            }
            probe.capabilities.clef.removalApis = removal;
            probe.capabilities.clef.selection = curScore ? {
                select: typeof curScore.selection.select,
                selectRange: typeof curScore.selection.selectRange,
                clear: typeof curScore.selection.clear,
                elements: typeof curScore.selection.elements
            } : "no-score";
        } catch (e) {
            probe.capabilities.clef.removalError = e.message || String(e);
        }

        // Segment access. firstSegment reported as "function" in 4.7.4, so
        // this records both the accessor kind and what the segment itself
        // offers once obtained.
        try {
            probe.capabilities.clef.firstSegmentKind =
                curScore ? typeof curScore.firstSegment : "no-score";
            var seg = null;
            if (curScore) {
                seg = (typeof curScore.firstSegment === "function")
                    ? curScore.firstSegment() : curScore.firstSegment;
            }
            probe.capabilities.clef.segment = seg ? {
                next: typeof seg.next,
                nextInMeasure: typeof seg.nextInMeasure,
                elementAt: typeof seg.elementAt,
                segmentType: typeof seg.segmentType,
                segmentTypeValue: (seg.segmentType !== undefined)
                    ? String(seg.segmentType) : null,
                tick: (seg.tick !== undefined) ? seg.tick : null,
                annotations: typeof seg.annotations
            } : "no-segment";

            // Walk a few segments and report every element found, so the
            // real route to a Clef is visible rather than inferred.
            var found = [];
            var walk = seg;
            var steps = 0;
            while (walk && steps < 40) {
                for (var t = 0; t < 8; t++) {
                    var el = null;
                    try {
                        el = (typeof walk.elementAt === "function")
                            ? walk.elementAt(t) : null;
                    } catch (e2) { el = null; }
                    if (el && el.type === Element.CLEF) {
                        found.push({
                            track: t,
                            tick: walk.tick,
                            type: el.type,
                            subtype: (el.subtype !== undefined) ? el.subtype : null,
                            generatedType: typeof el.generated,
                            generated: (el.generated !== undefined)
                                ? el.generated : null,
                            concertClefType: (el.concertClefType !== undefined)
                                ? el.concertClefType : null,
                            userName: (typeof el.userName === "function")
                                ? el.userName() : null
                        });
                    }
                }
                walk = (typeof walk.next === "function") ? walk.next() : walk.next;
                steps++;
            }
            probe.capabilities.clef.walkFound = found;
            probe.capabilities.clef.walkSteps = steps;
        } catch (e) {
            probe.capabilities.clef.segmentError = e.message || String(e);
        }

        // Which property on a Clef element is WRITABLE? subtype is
        // read-only in 4.7.4; MuseScore's Pid enum suggests the concert /
        // transposing pair, but the names are version-dependent.
        try {
            var writable = {};
            var candidates = ["subtype", "clefType", "clefTypeConcert",
                "clefTypeTransposing", "concertClefType",
                "transposingClefType"];
            for (var c = 0; c < candidates.length; c++) {
                var fresh = newElement(Element.CLEF);
                var name = candidates[c];
                var entry = { exists: typeof fresh[name] };
                try {
                    fresh[name] = 21;   // F / bass
                    entry.wrote = true;
                    entry.readBack = fresh[name];
                } catch (e3) {
                    entry.wrote = false;
                    entry.error = e3.message || String(e3);
                }
                writable[name] = entry;
            }
            probe.capabilities.clef.writableProps = writable;
        } catch (e) {
            probe.capabilities.clef.writableError = e.message || String(e);
        }

        try {
            probe.capabilities.clef.observed = collectClefs(null);
            probe.capabilities.clef.table = clefTypes;
        } catch (e) {
            probe.capabilities.clef.observedError = e.message || String(e);
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

        // Mid-measure clefs are almost always unintended -- MuseScore's
        // MIDI import inserts them to chase notes that stray out of a
        // staff's range. Surfacing them here makes them discoverable
        // without exporting and parsing MusicXML; getClefs has the rest.
        var allClefs = collectClefs(null);
        var midMeasure = [];
        var realClefs = 0;
        for (var c = 0; c < allClefs.length; c++) {
            if (allClefs[c].redundant) continue;  // system courtesy clefs
            realClefs++;
            if (!allClefs[c].atMeasureStart) midMeasure.push(allClefs[c]);
        }

        return {
            result: {
                title: curScore.title || "",
                partCount: parts.length,
                parts: parts,
                measureCount: countMeasures(),
                keySignature: keySig,
                timeSignature: timeSig,
                clefCount: realClefs,
                midMeasureClefs: midMeasure,
                pluginVersion: root.version
            }
        };
    }

    /// Every clef in the score, in tick order.
    /// Params: { staff?: int }  (omit for all staves)
    ///
    /// `atMeasureStart: false` marks a mid-measure clef change -- the
    /// kind MuseScore's MIDI import leaves behind, and the kind
    /// removeClef is meant to clear.
    function handleGetClefs(params) {
        var scoreErr = requireScore();
        if (scoreErr) return scoreErr;

        var staffFilter = null;
        if (params && params.staff !== undefined && params.staff !== null) {
            staffFilter = safeParseInt(params.staff);
            if (staffFilter === null) {
                return { error: "Invalid value for staff: " + params.staff };
            }
            if (staffFilter < 0 || staffFilter >= curScore.nstaves) {
                return { error: "Staff " + staffFilter + " out of range (0-" +
                    (curScore.nstaves - 1) + ")" };
            }
        }

        // Courtesy clefs at system starts outnumber real ones by an order
        // of magnitude, so they are hidden unless explicitly asked for.
        var includeRedundant = (params && params.includeRedundant === true);

        var all = collectClefs(staffFilter);
        var clefs = [];
        var redundantCount = 0;
        var midMeasureCount = 0;
        for (var i = 0; i < all.length; i++) {
            if (all[i].redundant) {
                redundantCount++;
                if (!includeRedundant) continue;
            }
            if (!all[i].atMeasureStart) midMeasureCount++;
            clefs.push(all[i]);
        }

        return {
            result: {
                clefs: clefs,
                count: clefs.length,
                midMeasureCount: midMeasureCount,
                redundantHidden: includeRedundant ? 0 : redundantCount
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

        // The clef governing this position: the last clef on this staff at
        // or before the cursor tick. Without it an agent cannot tell which
        // staff a pitch will actually read on after a mid-measure change.
        var governing = null;
        var staffClefs = collectClefs(cursorStaff);
        for (var i = 0; i < staffClefs.length; i++) {
            if (staffClefs[i].tick <= cursor.tick) {
                governing = staffClefs[i];
            } else {
                break;  // collectClefs is tick-ordered
            }
        }

        return {
            result: {
                measure: cursorMeasure,
                staff: cursorStaff,
                voice: cursorVoice,
                beat: beat,
                tick: cursor.tick,
                element: elementInfo,
                clef: governing
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
    /// Move the cursor to a staff, and optionally to a voice within it.
    /// Params: { staff, voice? }
    ///
    /// Voice is what makes independent two-voice writing on one staff
    /// possible (voice 0 is the upper/default voice in MuseScore's UI
    /// terms, "Voice 1").
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

        var voice = cursorVoice;
        if (params.voice !== undefined) {
            voice = safeParseInt(params.voice);
            if (voice === null || voice < 0 || voice > 3) {
                return { error: "voice must be 0-3, got: " + params.voice };
            }
        }

        cursorStaff = staffIndex;
        cursorVoice = voice;
        cursorTick = -1;
        lastWriteTick = -1;
        return {
            result: {
                measure: cursorMeasure,
                staff: cursorStaff,
                voice: cursorVoice
            }
        };
    }

    // ===================================================================
    // Command handlers -- score modification
    // ===================================================================

    /// Add a note at the current cursor position.
    ///
    /// Params: { pitch, duration?: { numerator, denominator },
    ///           advanceCursorAfterAction?: bool, addToChord?: bool,
    ///           tpc?: int }
    ///
    /// `addToChord` stacks the note onto the chord written by the
    /// previous addNote instead of advancing, which is how chords are
    /// built. `tpc` is the note's spelling (tonal pitch class), computed
    /// by the server with music21 -- without it MuseScore guesses from
    /// the key signature and cannot tell an ascending C-sharp from a
    /// descending D-flat.
    function handleAddNote(params) {
        var req = requireCursor();
        if (req.error) return req.error;
        var cursor = req.cursor;

        var parsed = parseNoteParams(params);
        if (parsed.error) return { error: parsed.error };

        var addToChord = (params.addToChord === true);
        // A chord tone joins the previous chord, so the cursor must stay.
        var advance = (params.advanceCursorAfterAction !== false) && !addToChord;
        var targetTick = addToChord
            ? (lastWriteTick >= 0 ? lastWriteTick : cursor.tick)
            : cursor.tick;
        if (addToChord) {
            // The previous addNote advanced past the chord it wrote, but
            // cursor.addNote(pitch, true) stacks onto the chord UNDER the
            // cursor -- so step back onto it first.
            cursor = cursorAtTick(cursorStaff, cursorVoice, targetTick);
            if (!cursor) return { error: "Could not position cursor" };
        }

        var spelled = false;
        // try/finally: never leave an open command group if addNote throws.
        curScore.startCmd("addNote");
        try {
            cursor.setDuration(parsed.numerator, parsed.denominator);
            cursor.addNote(parsed.pitch, addToChord);
            if (parsed.tpc !== null) {
                spelled = applyTpc(
                    noteAtTick(cursorStaff, cursorVoice, targetTick, parsed.pitch),
                    parsed.tpc);
            }
        } finally {
            curScore.endCmd();
        }

        if (!addToChord) lastWriteTick = targetTick;
        if (advance) {
            cursorMeasure = measureNumberAtTick(cursor.tick);
            cursorTick = cursor.tick;
        }

        return {
            result: {
                pitch: parsed.pitch,
                tpc: parsed.tpc,
                spelled: spelled,
                addedToChord: addToChord,
                duration: {
                    numerator: parsed.numerator,
                    denominator: parsed.denominator
                },
                measure: cursorMeasure,
                staff: cursorStaff,
                voice: cursorVoice
            }
        };
    }

    /// Validate the shared pitch/duration/tpc parameters of addNote.
    /// Returns { error } or { pitch, numerator, denominator, tpc }.
    function parseNoteParams(params) {
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

        var duration = parseDurationParams(params);
        if (duration.error) return { error: duration.error };

        var tpc = null;
        if (params.tpc !== undefined && params.tpc !== null) {
            tpc = safeParseInt(params.tpc);
            if (tpc === null || tpc < -1 || tpc > 33) {
                return { error: "tpc must be an integer -1..33, got: " + params.tpc };
            }
        }

        return {
            pitch: pitch,
            numerator: duration.numerator,
            denominator: duration.denominator,
            tpc: tpc
        };
    }

    /// Validate an optional { duration: { numerator, denominator } },
    /// defaulting to a quarter note. Returns { error } or the pair.
    function parseDurationParams(params) {
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
        return { numerator: numerator, denominator: denominator };
    }

    /// Add a rest at the current cursor position.
    /// Params: { duration?: { numerator, denominator },
    ///           advanceCursorAfterAction?: bool }
    function handleAddRest(params) {
        var req = requireCursor();
        if (req.error) return req.error;
        var cursor = req.cursor;

        if (typeof cursor.addRest !== "function") {
            return { error: "cursor.addRest is not available in this MuseScore build" };
        }
        var duration = parseDurationParams(params);
        if (duration.error) return { error: duration.error };
        var advance = (params.advanceCursorAfterAction !== false);

        curScore.startCmd("addRest");
        try {
            cursor.setDuration(duration.numerator, duration.denominator);
            cursor.addRest();
        } finally {
            curScore.endCmd();
        }

        lastWriteTick = -1;
        if (advance) {
            cursorMeasure = measureNumberAtTick(cursor.tick);
            cursorTick = cursor.tick;
        }

        return {
            result: {
                rest: true,
                duration: {
                    numerator: duration.numerator,
                    denominator: duration.denominator
                },
                measure: cursorMeasure,
                staff: cursorStaff,
                voice: cursorVoice
            }
        };
    }

    /// Rewrite the pitch and spelling of notes already in the score.
    ///
    /// Params: { staff, voice?, startMeasure, endMeasure,
    ///           edits: [{ oldPitch, newPitch, newTpc }] }
    ///
    /// Edits are positional: edit N applies to the Nth note of the
    /// staff+voice across the measure range, in the order defined by
    /// collectNotesInRange. Every `oldPitch` is verified against the
    /// score BEFORE anything is written, so a stale request (the score
    /// changed since the server's snapshot) aborts without a partial
    /// edit -- which matters because undo is broken in MuseScore 4.7.4.
    ///
    /// This is the transposition path: the server computes each new
    /// pitch and spelling with music21 and sends the result here.
    function handleSetPitches(params) {
        var scoreErr = requireScore();
        if (scoreErr) return scoreErr;

        if (!params.edits || params.edits.length === undefined) {
            return { error: "Missing required parameter: edits (array)" };
        }
        var staffIdx = safeParseInt(params.staff !== undefined ? params.staff : 0);
        var voice = safeParseInt(params.voice !== undefined ? params.voice : 0);
        var startMeasure = safeParseInt(params.startMeasure);
        var endMeasure = safeParseInt(
            params.endMeasure !== undefined ? params.endMeasure : params.startMeasure);

        if (staffIdx === null || voice === null ||
            startMeasure === null || endMeasure === null) {
            return { error: "Invalid range parameters" };
        }
        if (staffIdx < 0 || staffIdx >= curScore.nstaves) {
            return { error: "Staff " + staffIdx + " out of range (0-" +
                (curScore.nstaves - 1) + ")" };
        }
        if (voice < 0 || voice > 3) {
            return { error: "voice must be 0-3, got: " + voice };
        }
        var totalMeasures = countMeasures();
        if (startMeasure < 1 || endMeasure > totalMeasures ||
            startMeasure > endMeasure) {
            return { error: "Invalid measure range: " + startMeasure + "-" +
                endMeasure + " (score has " + totalMeasures + " measures)" };
        }

        var notes = collectNotesInRange(staffIdx, voice, startMeasure, endMeasure);
        if (notes.length !== params.edits.length) {
            return {
                error: "Edit count does not match the score: " +
                    params.edits.length + " edits for " + notes.length +
                    " notes in staff " + staffIdx + " voice " + voice +
                    " measures " + startMeasure + "-" + endMeasure +
                    ". The score changed since the snapshot; re-read and retry.",
                expectedNotes: notes.length,
                receivedEdits: params.edits.length
            };
        }

        // Pass 1 -- verify every note still holds the pitch the server saw,
        // and that each edit is internally complete.
        for (var i = 0; i < params.edits.length; i++) {
            var expected = safeParseInt(params.edits[i].oldPitch);
            if (expected === null) {
                return { error: "edits[" + i + "].oldPitch is not an integer" };
            }
            // MusicXML export writes a note's SPELLING (step/alter/octave
            // from tpc), not its MIDI number. Changing pitch without tpc
            // leaves the note internally inconsistent -- it still exports
            // as the old note. Both must be given together.
            if (params.edits[i].newPitch !== undefined &&
                params.edits[i].newPitch !== null &&
                (params.edits[i].newTpc === undefined ||
                 params.edits[i].newTpc === null)) {
                return {
                    error: "edits[" + i + "] sets newPitch without newTpc. " +
                        "MuseScore exports the spelling, not the MIDI pitch, " +
                        "so both must be supplied together."
                };
            }
            if (notes[i].pitch !== expected) {
                return {
                    error: "Note " + i + " is pitch " + notes[i].pitch +
                        ", expected " + expected +
                        ". The score changed since the snapshot; re-read and retry.",
                    index: i, found: notes[i].pitch, expected: expected
                };
            }
        }

        // Pass 2 -- apply. Verification passed, so this cannot half-fail
        // on a mismatch.
        var changed = 0;
        var spelled = 0;
        curScore.startCmd("setPitches");
        try {
            for (var j = 0; j < params.edits.length; j++) {
                var edit = params.edits[j];
                var newPitch = safeParseInt(edit.newPitch);
                if (newPitch !== null && newPitch >= 0 && newPitch <= 127) {
                    notes[j].pitch = newPitch;
                    changed++;
                }
                if (edit.newTpc !== undefined && edit.newTpc !== null) {
                    if (applyTpc(notes[j], safeParseInt(edit.newTpc))) spelled++;
                }
            }
        } finally {
            curScore.endCmd();
        }

        return {
            result: {
                staff: staffIdx, voice: voice,
                startMeasure: startMeasure, endMeasure: endMeasure,
                notesChanged: changed, notesSpelled: spelled
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

    /// Write a ClefType onto a Clef element.
    ///
    /// `subtype` is read-only in MuseScore 4.7.4; concertClefType and
    /// transposingClefType are the writable pair. Returns true when at
    /// least one assignment was accepted.
    function applyClefType(clef, subtype) {
        var applied = false;
        var names = ["concertClefType", "transposingClefType"];
        for (var i = 0; i < names.length; i++) {
            // typeof guards against silently creating a JS expando on a
            // build where the property does not exist -- an assignment to
            // an unknown name "succeeds" without touching the score.
            if (typeof clef[names[i]] === "number") {
                clef[names[i]] = subtype;
                applied = true;
            }
        }
        return applied;
    }

    /// Resolve a clef request to a ClefType integer.
    /// Accepts either { type: "bass" } or { subtype: 20 }.
    function resolveClefSubtype(params) {
        if (params.subtype !== undefined && params.subtype !== null) {
            var raw = safeParseInt(params.subtype);
            if (raw === null || raw < 0) {
                return { error: "Invalid value for subtype: " + params.subtype };
            }
            return { subtype: raw, name: clefNameFromSubtype(raw) };
        }
        if (params.type === undefined || params.type === null || params.type === "") {
            return { error: "Missing required parameter: type (or subtype). " +
                "Valid types: " + Object.keys(clefTypes).join(", ") };
        }
        var value = clefTypes[params.type];
        if (value === undefined) {
            return { error: "Unknown clef type: " + params.type +
                ". Valid types: " + Object.keys(clefTypes).join(", ") +
                " (or pass an explicit ClefType integer as 'subtype')" };
        }
        return { subtype: value, name: params.type };
    }

    /// Insert a clef at the current cursor position.
    /// Params: { type?: string, subtype?: int }
    ///
    /// The clef lands on the cursor's staff at the cursor's tick, so a
    /// mid-measure clef change is written by seeking within the measure
    /// first. Position with goToStaff/goToMeasure as usual.
    function handleSetClef(params) {
        var req = requireCursor();
        if (req.error) return req.error;
        var cursor = req.cursor;

        var resolved = resolveClefSubtype(params);
        if (resolved.error) return { error: resolved.error };

        if (!cursor.segment) {
            return { error: "No valid segment at cursor position" };
        }

        var postAddSubtype = null;
        curScore.startCmd("setClef");
        try {
            var clef = newElement(Element.CLEF);
            // Element.subtype is READ-ONLY in MuseScore 4.7.4 -- assigning
            // to it throws. The writable pair is concertClefType /
            // transposingClefType, and both are set so the clef reads the
            // same in concert-pitch and transposed views.
            applyClefType(clef, resolved.subtype);
            cursor.add(clef);
            // cursor.add clones the element for several element types in
            // MuseScore 4 and the clone loses values assigned beforehand
            // (this is what corrupts setKeySignature and setTempo).
            // Re-assign and report what actually stuck, so a caller can
            // tell a real write from a silently dropped one.
            applyClefType(clef, resolved.subtype);
            postAddSubtype = (clef.subtype !== undefined) ? clef.subtype : null;
        } finally {
            curScore.endCmd();
        }

        return {
            result: {
                type: resolved.name,
                subtype: resolved.subtype,
                postAddSubtype: postAddSubtype,
                measure: cursorMeasure,
                staff: cursorStaff,
                tick: cursor.tick
            }
        };
    }

    /// Remove clefs from the score.
    ///
    /// Params: { staff?: int, measure?: int, startMeasure?, endMeasure?,
    ///           tick?: int, midMeasureOnly?: bool, force?: bool }
    ///
    /// Every filter is optional and they intersect; with none given this
    /// removes nothing unless midMeasureOnly is set, because deleting
    /// every clef in a score is never what anyone means.
    ///
    /// The staff-defining clef at tick 0 is refused unless force is true:
    /// removing it leaves the staff with no clef at all.
    ///
    /// The motivating case is MuseScore's MIDI import, which inserts
    /// mid-measure clef changes to chase notes that stray out of range.
    /// Once those notes are moved to the right staff the clefs remain and
    /// have to be cleared: { staff: 1, midMeasureOnly: true }.
    function handleRemoveClef(params) {
        var plan = planClefRemoval(params);
        if (plan.error) return plan.error;
        if (plan.doomed.length === 0) return plan.emptyResult;

        curScore.startCmd("removeClef");
        try {
            return applyClefRemoval(plan);
        } finally {
            curScore.endCmd();
        }
    }

    /// Validate and resolve which clefs a removeClef request targets,
    /// without touching the score. Returns { error } | { doomed, ... }.
    function planClefRemoval(params) {
        var scoreErr = requireScore();
        if (scoreErr) return { error: scoreErr };

        var midMeasureOnly = (params.midMeasureOnly === true);
        var force = (params.force === true);

        var staffFilter = null;
        if (params.staff !== undefined && params.staff !== null) {
            staffFilter = safeParseInt(params.staff);
            if (staffFilter === null) {
                return { error: { error: "Invalid value for staff: " + params.staff } };
            }
            if (staffFilter < 0 || staffFilter >= curScore.nstaves) {
                return { error: { error: "Staff " + staffFilter +
                    " out of range (0-" + (curScore.nstaves - 1) + ")" } };
            }
        }

        var startMeasure = null;
        var endMeasure = null;
        if (params.measure !== undefined && params.measure !== null) {
            startMeasure = safeParseInt(params.measure);
            endMeasure = startMeasure;
        } else {
            if (params.startMeasure !== undefined && params.startMeasure !== null) {
                startMeasure = safeParseInt(params.startMeasure);
            }
            if (params.endMeasure !== undefined && params.endMeasure !== null) {
                endMeasure = safeParseInt(params.endMeasure);
            }
        }
        if ((params.measure !== undefined && startMeasure === null) ||
            (params.startMeasure !== undefined && startMeasure === null) ||
            (params.endMeasure !== undefined && endMeasure === null)) {
            return { error: { error: "Invalid measure range parameters" } };
        }

        var tickFilter = null;
        if (params.tick !== undefined && params.tick !== null) {
            tickFilter = safeParseInt(params.tick);
            if (tickFilter === null) {
                return { error: { error: "Invalid value for tick: " + params.tick } };
            }
        }

        var noFilters = (staffFilter === null && startMeasure === null &&
            endMeasure === null && tickFilter === null && !midMeasureOnly);
        if (noFilters && !force) {
            return { error: { error: "removeClef needs at least one filter " +
                "(staff, measure, startMeasure/endMeasure, tick, or " +
                "midMeasureOnly). Removing every clef in the score is " +
                "almost certainly not intended; pass force: true if it is." } };
        }

        // Clef removal is IMPOSSIBLE in MuseScore Studio 4.7.4, verified
        // 2026-07-27. Score-level removal does not exist (removeElement,
        // deleteElement, remove, cmdRemove, removeSelection are all
        // undefined) and the selection route cannot stand in for it:
        // curScore.selection.select(clef) returns false for a Clef, so
        // select+delete, select(add=false)+delete and
        // select+delete-selection all leave the clef in place.
        //
        // Refused up front rather than attempted, because the attempt
        // cannot be distinguished from success by the caller's reply
        // alone. setClef DOES replace a clef at the same position, so an
        // unwanted clef can be overwritten even though it cannot be
        // deleted -- that is the documented workaround.
        if (params.__experimental !== true) {
            return { error: { error: "removeClef is disabled: MuseScore " +
                "Studio 4.7.4 exposes no way to delete a clef from a " +
                "plugin (curScore.removeElement is undefined and " +
                "selection.select() returns false for a Clef, so " +
                "cmd(\"delete\") has nothing to act on). Delete the clef " +
                "in the MuseScore UI, or use setClef to overwrite it -- " +
                "setClef replaces a clef at the same position rather than " +
                "stacking. Pass __experimental: true to probe anyway." } };
        }

        var entries = collectClefEntries(staffFilter);
        var doomed = [];
        var skippedHeader = 0;
        for (var i = 0; i < entries.length; i++) {
            var info = entries[i].info;
            // A courtesy clef at a system start is laid out, not authored.
            // Deleting one deletes the clef it restates.
            if (info.redundant) continue;
            if (midMeasureOnly && info.atMeasureStart) continue;
            if (startMeasure !== null && info.measure < startMeasure) continue;
            if (endMeasure !== null && info.measure > endMeasure) continue;
            if (tickFilter !== null && info.tick !== tickFilter) continue;
            if (info.tick === 0 && !force) {
                skippedHeader++;
                continue;
            }
            doomed.push(entries[i]);
        }

        return {
            doomed: doomed,
            skippedHeader: skippedHeader,
            emptyResult: {
                result: {
                    removed: 0,
                    clefs: [],
                    skippedStaffDefining: skippedHeader
                }
            }
        };
    }

    /// Delete the clefs a plan selected. The caller owns the command
    /// group, so this is safe to call from inside processSequence.
    function applyClefRemoval(plan) {
        var removedInfos = [];
        var failed = [];
        // Reverse order: removing a clef re-lays-out the score, and taking
        // the later ones first keeps the earlier entries valid.
        var diagnostics = [];
        for (var j = plan.doomed.length - 1; j >= 0; j--) {
            var outcome = { ok: false, attempts: [] };
            try {
                outcome = removeOneElement(
                    plan.doomed[j].element, plan.doomed[j].info);
            } catch (e) {
                outcome = { ok: false, error: e.message || String(e), attempts: [] };
            }
            if (outcome.ok) {
                removedInfos.unshift(plan.doomed[j].info);
                if (diagnostics.length === 0) diagnostics.push(outcome.strategy);
            } else {
                failed.unshift(plan.doomed[j].info);
                if (diagnostics.length === 0) {
                    diagnostics.push({ failedAttempts: outcome.attempts });
                }
            }
        }
        var result = {
            removed: removedInfos.length,
            clefs: removedInfos,
            skippedStaffDefining: plan.skippedHeader,
            strategy: diagnostics.length > 0 ? diagnostics[0] : null
        };
        if (failed.length > 0) {
            result.failed = failed;
            result.note = "Some clefs could not be removed. Deleting them " +
                "in the MuseScore UI is the reliable route.";
        }
        return { result: result };
    }

    /// Delete one element, by whichever route this build supports.
    ///
    /// MuseScore 4.7.4 exposes no score-level removal, so the routes are
    /// selection-based and none is documented to work on a Clef. Each is
    /// tried and then VERIFIED against the score -- a reply of "deleted"
    /// that leaves the clef in place is the failure mode to avoid here.
    ///
    /// Every route clears the selection first. Without that, a failed
    /// select would leave the previous selection standing and cmd("delete")
    /// would delete whatever was selected before -- notes, most likely.
    /// Range selection is deliberately not attempted for the same reason:
    /// a range around the clef contains the music too.
    function removeOneElement(element, info) {
        var attempts = [];

        if (typeof curScore.removeElement === "function") {
            try {
                curScore.removeElement(element);
                if (!clefStillPresent(info)) {
                    return { ok: true, strategy: "removeElement", attempts: attempts };
                }
                attempts.push({ strategy: "removeElement", selected: null });
            } catch (e) {
                attempts.push({ strategy: "removeElement", error: e.message || String(e) });
            }
        }

        var selectionRoutes = [
            { name: "select+delete", args: 1, action: "delete" },
            { name: "select(add=false)+delete", args: 2, action: "delete" },
            { name: "select+delete-selection", args: 1, action: "delete-selection" }
        ];
        for (var i = 0; i < selectionRoutes.length; i++) {
            var route = selectionRoutes[i];
            try {
                curScore.selection.clear();
                var selected = (route.args === 2)
                    ? curScore.selection.select(element, false)
                    : curScore.selection.select(element);
                // The return value is NOT trusted as a gate: a build may
                // select successfully and return undefined. The score is
                // the authority, so the command runs either way -- safe
                // because the selection was cleared first.
                cmd(route.action);
                if (!clefStillPresent(info)) {
                    return { ok: true, strategy: route.name, attempts: attempts };
                }
                attempts.push({ strategy: route.name, selected: String(selected) });
            } catch (e) {
                attempts.push({ strategy: route.name, error: e.message || String(e) });
            }
        }
        return { ok: false, strategy: null, attempts: attempts };
    }

    /// Is a clef still in the score at the position an entry described?
    /// Re-walks rather than trusting a stale element handle.
    function clefStillPresent(info) {
        var entries = collectClefEntries(info.staff);
        for (var i = 0; i < entries.length; i++) {
            if (entries[i].info.tick === info.tick) return true;
        }
        return false;
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
                var seqVoice = cursorVoice;
                if (params.voice !== undefined) {
                    seqVoice = safeParseInt(params.voice);
                    if (seqVoice === null || seqVoice < 0 || seqVoice > 3)
                        return { error: "voice must be 0-3, got: " + params.voice };
                }
                cursorStaff = staffIdx;
                cursorVoice = seqVoice;
                cursorTick = -1;
                lastWriteTick = -1;
                return {
                    result: { measure: cursorMeasure, staff: cursorStaff, voice: cursorVoice },
                    newCursor: positionedCursor()
                };
            }

            case "addNote": {
                var noteParams = parseNoteParams(params);
                if (noteParams.error) return { error: noteParams.error };
                if (!cursor) return { error: "Could not position cursor" };
                var seqAddToChord = (params.addToChord === true);
                var advance = (params.advanceCursorAfterAction !== false) && !seqAddToChord;
                var seqTargetTick = seqAddToChord
                    ? (lastWriteTick >= 0 ? lastWriteTick : cursor.tick)
                    : cursor.tick;
                if (seqAddToChord) {
                    // Step back onto the chord written by the previous step.
                    cursor = cursorAtTick(cursorStaff, cursorVoice, seqTargetTick);
                    if (!cursor) return { error: "Could not position cursor" };
                }

                cursor.setDuration(noteParams.numerator, noteParams.denominator);
                cursor.addNote(noteParams.pitch, seqAddToChord);
                var seqSpelled = false;
                if (noteParams.tpc !== null) {
                    seqSpelled = applyTpc(
                        noteAtTick(cursorStaff, cursorVoice, seqTargetTick, noteParams.pitch),
                        noteParams.tpc);
                }

                if (!seqAddToChord) lastWriteTick = seqTargetTick;
                if (advance) {
                    cursorMeasure = measureNumberAtTick(cursor.tick);
                    cursorTick = cursor.tick;
                }
                return {
                    result: {
                        pitch: noteParams.pitch,
                        tpc: noteParams.tpc,
                        spelled: seqSpelled,
                        addedToChord: seqAddToChord,
                        duration: {
                            numerator: noteParams.numerator,
                            denominator: noteParams.denominator
                        },
                        measure: cursorMeasure,
                        voice: cursorVoice
                    }
                };
            }

            case "addRest": {
                if (!cursor) return { error: "Could not position cursor" };
                if (typeof cursor.addRest !== "function")
                    return { error: "cursor.addRest is not available in this MuseScore build" };
                var restDuration = parseDurationParams(params);
                if (restDuration.error) return { error: restDuration.error };
                var restAdvance = (params.advanceCursorAfterAction !== false);
                cursor.setDuration(restDuration.numerator, restDuration.denominator);
                cursor.addRest();
                lastWriteTick = -1;
                if (restAdvance) {
                    cursorMeasure = measureNumberAtTick(cursor.tick);
                    cursorTick = cursor.tick;
                }
                return {
                    result: {
                        rest: true,
                        duration: {
                            numerator: restDuration.numerator,
                            denominator: restDuration.denominator
                        },
                        measure: cursorMeasure,
                        voice: cursorVoice
                    }
                };
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

            case "setClef": {
                var clefResolved = resolveClefSubtype(params);
                if (clefResolved.error) return { error: clefResolved.error };
                var clefCursor = positionedCursor();
                if (!clefCursor) return { error: "Could not position cursor" };
                if (!clefCursor.segment) return { error: "No valid segment at cursor position" };
                var newClef = newElement(Element.CLEF);
                // subtype is read-only; see applyClefType.
                applyClefType(newClef, clefResolved.subtype);
                clefCursor.add(newClef);
                applyClefType(newClef, clefResolved.subtype);
                return {
                    result: {
                        type: clefResolved.name,
                        subtype: clefResolved.subtype,
                        measure: cursorMeasure,
                        staff: cursorStaff
                    }
                };
            }

            case "removeClef": {
                // processSequence owns the command group, so this uses the
                // split plan/apply pair rather than handleRemoveClef (which
                // opens a group of its own).
                var removalPlan = planClefRemoval(params);
                if (removalPlan.error) return removalPlan.error;
                if (removalPlan.doomed.length === 0) return removalPlan.emptyResult;
                return applyClefRemoval(removalPlan);
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
