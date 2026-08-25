"""Regenerate the notation-vocabulary probe (import fidelity).

Twenty bars of piano solo exercising ~46 notation constructs, one cluster per
bar, each bar labelled. Open the output in MuseScore (or convert it with the
CLI) and diff it back to learn what this MuseScore build's MusicXML importer
understands.

    python notation_probe.py [OUT.musicxml]
    python ../../musescore-bridge/scripts/verify_fragment.py OUT.musicxml

Last run: MuseScore Studio 4.7.4 -- all but four constructs survived intact.
The recorded result lives in musescore-bridge/authoring-musicxml.md.
"""

import os
import sys

sys.path.insert(
    0,
    os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "..",
        "..",
        "musescore-bridge",
        "scripts",
    ),
)
import mxbuild as X  # noqa: E402
from mxbuild import *  # noqa: F401,F403,E402

Q, H, W, E, S = 840, 1680, 3360, 420, 210
BAR44, BAR34, BAR78 = 3360, 2520, 2940
DIV = X.DIV

root, part = new_score("Notation Vocabulary Probe")

# =====================================================================
# bar 1 - clefs, key, meter, tempo, rehearsal mark, dynamic, text, slur,
#         fingering, arpeggiated chord
# =====================================================================
m = measure(part, 1)
attributes(
    m,
    divisions=DIV,
    fifths=0,
    time=("4", "4"),
    staves=2,
    clefs={1: ("G", "2"), 2: ("F", "4")},
)
direction(m, rehearsal("A"), staff=1)
direction(m, metronome("quarter", 88), staff=1, sound={"tempo": 88})
direction(m, words("Andante", font_weight="bold"), staff=1)
direction(m, dynamic("p"), staff=1, placement="below")
direction(m, words("dolce", font_style="italic"), staff=1, placement="below")
label(m, "1 slur/fingering/arpeggio")
for i, (st, oc) in enumerate([("C", 5), ("D", 5), ("E", 5), ("F", 5)]):
    note(
        m,
        st,
        oc,
        slur=[("start", 1)] if i == 0 else ([("stop", 1)] if i == 3 else None),
        fingering=str(i + 1),
    )
backup(m, BAR44)
for i, (st, oc) in enumerate([("C", 3), ("E", 3), ("G", 3)]):
    note(
        m,
        st,
        oc,
        dur=W,
        type_="whole",
        voice=5,
        staff=2,
        chord=(i > 0),
        arpeggiate=True,
    )

# =====================================================================
# bar 2 - tie across barline, articulations
# =====================================================================
m = measure(part, 2)
label(m, "2 tie + articulations")
note(m, "G", 5, dur=H, type_="half", tie=["start"])
note(m, "C", 5, artic=["staccatissimo"])
note(m, "B", 4, artic=["detached-legato"])
backup(m, BAR44)
for st, oc, a in [
    ("C", 3, "staccato"),
    ("E", 3, "accent"),
    ("G", 3, "tenuto"),
    ("C", 4, "strong-accent"),
]:
    note(m, st, oc, voice=5, staff=2, artic=[a])

# =====================================================================
# bar 3 - tie stop, triplet, crescendo hairpin
# =====================================================================
m = measure(part, 3)
label(m, "3 triplet + hairpin")
direction(m, wedge("crescendo"), staff=1, placement="below")
note(m, "G", 5, dur=H, type_="half", tie=["stop"])
for i, st in enumerate(["E", "F", "G"]):
    note(
        m,
        st,
        5,
        dur=280,
        type_="eighth",
        tmod=(3, 2, "eighth"),
        tuplet="start" if i == 0 else ("stop" if i == 2 else None),
    )
note(m, "A", 5)
backup(m, BAR44)
for st, oc in [("F", 3), ("A", 3), ("C", 4), ("A", 3)]:
    note(m, st, oc, voice=5, staff=2)

# =====================================================================
# bar 4 - grace note, grace chord, mordents, dynamic f
# =====================================================================
m = measure(part, 4)
label(m, "4 grace notes + mordents")
direction(m, wedge("stop"), staff=1, placement="below")
direction(m, dynamic("f"), staff=1, placement="below")
note(m, "B", 4, type_="eighth", grace={"slash": "yes"})
note(m, "C", 6, orn=["mordent"])
note(m, "D", 5, type_="eighth", grace={})
note(m, "F", 5, type_="eighth", grace={}, chord=True)
note(m, "E", 5, orn=["inverted-mordent"])
note(m, "G", 5, dur=H, type_="half")
backup(m, BAR44)
note(m, "C", 3, dur=W, type_="whole", voice=5, staff=2)

# =====================================================================
# bar 5 - trill with wavy line, turn, delayed turn, pedal down
# =====================================================================
m = measure(part, 5)
label(m, "5 trill/turn + pedal")
direction(m, rehearsal("B"), staff=1)
direction(m, pedal("start"), staff=2, placement="below")
note(
    m, "C", 5, dur=H, type_="half", orn=["trill-mark", ("wavy-line", {"type": "start"})]
)
note(m, "D", 5, orn=[("wavy-line", {"type": "stop"}), "turn"])
note(m, "E", 5, orn=["delayed-turn"])
backup(m, BAR44)
note(m, "C", 3, dur=W, type_="whole", voice=5, staff=2)

# =====================================================================
# bar 6 - quintuplet, septuplet, pedal change
# =====================================================================
m = measure(part, 6)
label(m, "6 quintuplet + septuplet")
direction(m, pedal("change"), staff=2, placement="below")
for i, st in enumerate(["C", "D", "E", "F", "G"]):
    note(
        m,
        st,
        5,
        dur=168,
        type_="16th",
        tmod=(5, 4, "16th"),
        tuplet="start" if i == 0 else ("stop" if i == 4 else None),
    )
for i, st in enumerate(["A", "G", "F", "E", "D", "C", "B"]):
    note(
        m,
        st,
        5 if st != "B" else 4,
        dur=120,
        type_="16th",
        tmod=(7, 4, "16th"),
        tuplet="start" if i == 0 else ("stop" if i == 6 else None),
    )
note(m, "C", 5, dur=H, type_="half")
backup(m, BAR44)
note(m, "G", 2, dur=W, type_="whole", voice=5, staff=2)

# =====================================================================
# bar 7 - 8va octave shift, glissando
# =====================================================================
m = measure(part, 7)
label(m, "7 8va + glissando")
direction(m, octave_shift("down"), staff=1)
note(m, "C", 6)
note(m, "E", 6)
note(m, "G", 6, gliss=["start", "gliss."])
note(m, "C", 7, gliss=["stop"])
direction(m, octave_shift("stop"), staff=1)
direction(m, pedal("stop"), staff=2, placement="below")
backup(m, BAR44)
note(m, "C", 3, dur=W, type_="whole", voice=5, staff=2)

# =====================================================================
# bar 8 - clef change on the upper staff
# =====================================================================
m = measure(part, 8)
attributes(m, clefs={1: ("F", "4")})
label(m, "8 clef change (RH bass)")
for st, oc in [("C", 3), ("E", 3), ("G", 3), ("C", 4)]:
    note(m, st, oc)
backup(m, BAR44)
note(m, "C", 2, dur=W, type_="whole", voice=5, staff=2)

# =====================================================================
# bar 9 - clef back, cross-staff notes (voice 1 written on staff 2)
# =====================================================================
m = measure(part, 9)
attributes(m, clefs={1: ("G", "2")})
label(m, "9 cross-staff")
note(m, "C", 5)
note(m, "E", 3, staff=2)
note(m, "G", 3, staff=2)
note(m, "C", 5)
backup(m, BAR44)
note(m, "C", 2, dur=W, type_="whole", voice=5, staff=2)

# =====================================================================
# bar 10 - key change, meter change, double barline
# =====================================================================
m = measure(part, 10)
attributes(m, fifths=-3, time=("3", "4"))
label(m, "10 key + meter change")
note(m, "E", 5, alter=-1)
note(m, "G", 5)
note(m, "B", 5, alter=-1)
backup(m, BAR34)
note(m, "E", 3, alter=-1, dur=H, type_="half", voice=5, staff=2)
note(m, "G", 3, voice=5, staff=2)
barline(m, style="light-light")

# =====================================================================
# bar 11 - two voices per staff, fermata
# =====================================================================
m = measure(part, 11)
label(m, "11 two voices per staff")
note(m, "G", 5, dur=BAR34, type_="half", dots=1, stem="up", fermata=True)
backup(m, BAR34)
for st, oc in [("E", 5), ("D", 5), ("C", 5)]:
    note(m, st, oc, alter=-1 if st == "E" else None, voice=2, stem="down")
backup(m, BAR34)
note(m, "G", 3, dur=H, type_="half", voice=5, staff=2, stem="up")
note(m, "B", 3, alter=-1, voice=5, staff=2, stem="up")
backup(m, BAR34)
note(m, "C", 3, dur=BAR34, type_="half", dots=1, voice=6, staff=2, stem="down")

# =====================================================================
# bar 12 - repeat start, first ending, chord symbols
# =====================================================================
m = measure(part, 12)
barline(
    m, location="left", style="heavy-light", repeat="forward", ending=("1", "start")
)
label(m, "12 repeat + volta + chord symbols")
harmony(m, "C", "minor-seventh")
note(m, "C", 5)
harmony(m, "F", "dominant")
note(m, "E", 5, alter=-1)
harmony(m, "B", "major", alter=-1)
note(m, "G", 5)
backup(m, BAR34)
note(m, "C", 3, dur=BAR34, type_="half", dots=1, voice=5, staff=2)
barline(
    m, location="right", style="light-heavy", repeat="backward", ending=("1", "stop")
)

# =====================================================================
# bar 13 - second ending
# =====================================================================
m = measure(part, 13)
barline(m, location="left", ending=("2", "start"))
label(m, "13 second ending")
note(m, "C", 5)
note(m, "E", 5, alter=-1)
note(m, "C", 6)
backup(m, BAR34)
note(m, "C", 3, dur=BAR34, type_="half", dots=1, voice=5, staff=2)
barline(m, location="right", ending=("2", "discontinue"))

# =====================================================================
# bar 14 - double sharp, double flat, cautionary accidental
# =====================================================================
m = measure(part, 14)
label(m, "14 accidentals")
note(m, "C", 5, alter=2, accidental=("double-sharp", {}))
note(m, "B", 4, alter=-2, accidental=("flat-flat", {}))
note(m, "F", 5, accidental=("natural", {"parentheses": "yes"}))
backup(m, BAR34)
note(m, rest=True, measure_rest=True, dur=BAR34, type_=None, voice=5, staff=2)

# =====================================================================
# bar 15 - noteheads, tremolo
# =====================================================================
m = measure(part, 15)
label(m, "15 noteheads + tremolo")
note(m, "C", 5, notehead="x")
note(m, "E", 5, alter=-1, notehead="diamond")
note(m, "G", 5, tremolo=("single", 3))
backup(m, BAR34)
note(m, "C", 3, voice=5, staff=2, tremolo=("single", 2))
note(m, "G", 3, dur=H, type_="half", voice=5, staff=2)

# =====================================================================
# bar 16 - breath mark, caesura, rit. with dashed line
# =====================================================================
m = measure(part, 16)
label(m, "16 breath/caesura + rit.")
direction(m, words("rit.", font_style="italic"), staff=1)
direction(m, dashes("start"), staff=1)
note(m, "C", 5, artic=["breath-mark"])
note(m, "D", 5, artic=["caesura"])
note(m, "E", 5, alter=-1)
backup(m, BAR34)
note(m, "C", 3, dur=BAR34, type_="half", dots=1, voice=5, staff=2)

# =====================================================================
# bar 17 - 8vb on the lower staff, dashes stop
# =====================================================================
m = measure(part, 17)
label(m, "17 8vb (lower staff)")
direction(m, dashes("stop"), staff=1)
direction(m, octave_shift("up"), staff=2, placement="below")
note(m, rest=True, measure_rest=True, dur=BAR34, type_=None)
backup(m, BAR34)
note(m, "C", 2, voice=5, staff=2)
note(m, "E", 2, alter=-1, voice=5, staff=2)
note(m, "G", 2, voice=5, staff=2)
direction(m, octave_shift("stop"), staff=2, placement="below")

# =====================================================================
# bar 18 - 7/8 meter, quintuplet of eighths
# =====================================================================
m = measure(part, 18)
attributes(m, time=("7", "8"))
direction(m, rehearsal("C"), staff=1)
label(m, "18 7/8 + quintuplet")
for i, (st, oc) in enumerate([("C", 5), ("D", 5), ("E", 5), ("F", 5), ("G", 5)]):
    note(
        m,
        st,
        oc,
        alter=-1 if st == "E" else None,
        dur=336,
        type_="eighth",
        tmod=(5, 4, "eighth"),
        tuplet="start" if i == 0 else ("stop" if i == 4 else None),
    )
for st, oc in [("A", 5), ("G", 5), ("F", 5)]:
    note(m, st, oc, alter=-1 if st == "A" else None, dur=E, type_="eighth")
backup(m, BAR78)
note(m, "C", 3, dur=1260, type_="quarter", dots=1, voice=5, staff=2)
note(m, "G", 3, voice=5, staff=2)
note(m, "C", 4, voice=5, staff=2)

# =====================================================================
# bar 19 - segno, coda, D.S. al Coda, a tempo
# =====================================================================
m = measure(part, 19)
label(m, "19 segno/coda + D.S.")
direction(m, segno(), staff=1, sound={"segno": "segno"})
direction(m, coda(), staff=1, sound={"coda": "coda"})
direction(
    m, words("D.S. al Coda", font_weight="bold"), staff=1, sound={"dalsegno": "segno"}
)
direction(m, words("a tempo", font_style="italic"), staff=1, placement="below")
note(m, "C", 5, dur=H, type_="half")
note(m, "E", 5, alter=-1, dur=1260, type_="quarter", dots=1)
backup(m, BAR78)
note(m, "C", 3, dur=H, type_="half", voice=5, staff=2)
note(m, "C", 3, dur=1260, type_="quarter", dots=1, voice=5, staff=2)

# =====================================================================
# bar 20 - arpeggiate vs non-arpeggiate, fermata, final barline
# =====================================================================
m = measure(part, 20)
label(m, "20 arpeggio + final")
for i, (st, oc, al) in enumerate([("C", 5, None), ("E", 5, -1), ("G", 5, None)]):
    note(m, st, oc, alter=al, dur=H, type_="half", chord=(i > 0), arpeggiate=True)
for i, (st, oc, al) in enumerate([("C", 5, None), ("F", 5, None), ("A", 5, -1)]):
    note(
        m,
        st,
        oc,
        alter=al,
        dur=1260,
        type_="quarter",
        dots=1,
        chord=(i > 0),
        arpeggiate="non",
        fermata=(i == 2),
    )
backup(m, BAR78)
for i, (st, oc) in enumerate([("C", 2), ("G", 2)]):
    note(m, st, oc, dur=H, type_="half", voice=5, staff=2, chord=(i > 0))
for i, (st, oc) in enumerate([("F", 2), ("C", 3)]):
    note(
        m,
        st,
        oc,
        dur=1260,
        type_="quarter",
        dots=1,
        voice=5,
        staff=2,
        chord=(i > 0),
        fermata=(i == 1),
    )
barline(m, style="light-heavy")


out = sys.argv[1] if len(sys.argv) > 1 else "notation_probe.musicxml"
write(root, out)
expected = {
    **{n: BAR44 for n in range(1, 10)},
    **{n: BAR34 for n in range(10, 18)},
    **{n: BAR78 for n in range(18, 21)},
}
print(f"wrote {out} | bad measure lengths: {check_lengths(out, expected)}")
