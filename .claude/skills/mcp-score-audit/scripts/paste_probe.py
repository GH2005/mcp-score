"""Regenerate the paste-test fragment (what survives copy-paste).

Starts in the state the target document is in at bar 20 (7/8, three flats,
treble over bass) so that "unchanged" is the baseline, and every change made
inside the fragment is a deliberate test of what survives a copy-paste
between documents rather than a file import.
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
from mxbuild import (  # noqa: E402
    DIV,
    attributes,
    backup,
    barline,
    check_lengths,
    dashes,
    direction,
    dynamic,
    harmony,
    label,
    measure,
    metronome,
    new_score,
    note,
    octave_shift,
    pedal,
    rehearsal,
    wedge,
    words,
    write,
)

Q, E, H = 840, 420, 1680
B78, B44 = 2940, 3360  # 7/8 and 4/4 bars, in divisions

root, part = new_score("Paste Test Fragment")

# ---------------------------------------------------------------- bar 1
# baseline: slur, fingering, dynamic, hairpin, tie out to bar 2
m = measure(part, 1)
attributes(
    m,
    divisions=DIV,
    fifths=-3,
    time=("7", "8"),
    staves=2,
    clefs={1: ("G", "2"), 2: ("F", "4")},
)
label(m, "P1 slur/fingering/hairpin/tie")
direction(m, dynamic("mf"), staff=1, placement="below")
direction(m, wedge("crescendo"), staff=1, placement="below")
note(m, "E", 5, alter=-1, slur=[("start", 1)], fingering="1")
note(m, "F", 5, fingering="2")
note(m, "G", 5, slur=[("stop", 1)], fingering="3")
note(m, "A", 5, alter=-1, dur=E, type_="eighth", tie=["start"])
backup(m, B78)
note(m, "C", 3, dur=1260, type_="quarter", dots=1, voice=5, staff=2)
note(m, "E", 3, alter=-1, voice=5, staff=2)
note(m, "G", 3, voice=5, staff=2)

# ---------------------------------------------------------------- bar 2
# tie lands, articulations, hairpin stop
m = measure(part, 2)
label(m, "P2 tie stop + articulations")
direction(m, wedge("stop"), staff=1, placement="below")
direction(m, dynamic("f"), staff=1, placement="below")
note(m, "A", 5, alter=-1, dur=E, type_="eighth", tie=["stop"])
note(m, "G", 5, artic=["staccato"])
note(m, "F", 5, artic=["accent"])
note(m, "E", 5, alter=-1, artic=["tenuto"])
backup(m, B78)
note(m, "C", 3, voice=5, staff=2, artic=["strong-accent"])
note(m, "G", 3, voice=5, staff=2)
note(m, "C", 4, voice=5, staff=2)
note(m, "G", 3, dur=E, type_="eighth", voice=5, staff=2)

# ---------------------------------------------------------------- bar 3
# CLEF CHANGE on the upper staff
m = measure(part, 3)
attributes(m, clefs={1: ("F", "4")})
label(m, "P3 CLEF CHANGE (RH bass)")
note(m, "C", 3)
note(m, "E", 3, alter=-1)
note(m, "G", 3)
note(m, "C", 4, dur=E, type_="eighth")
backup(m, B78)
note(m, "C", 2, dur=1260, type_="quarter", dots=1, voice=5, staff=2)
note(m, "G", 2, voice=5, staff=2)
note(m, "C", 3, voice=5, staff=2)

# ---------------------------------------------------------------- bar 4
# clef back + KEY CHANGE to three sharps
m = measure(part, 4)
attributes(m, fifths=3, clefs={1: ("G", "2")})
label(m, "P4 KEY CHANGE (3 sharps)")
note(m, "A", 5)
note(m, "C", 6, alter=1)
note(m, "E", 6)
note(m, "A", 6, dur=E, type_="eighth")
backup(m, B78)
note(m, "A", 2, dur=1260, type_="quarter", dots=1, voice=5, staff=2)
note(m, "E", 3, voice=5, staff=2)
note(m, "A", 3, voice=5, staff=2)

# ---------------------------------------------------------------- bar 5
# REPEAT + VOLTA 1 + chord symbols + rehearsal mark + tempo + text
m = measure(part, 5)
barline(
    m, location="left", style="heavy-light", repeat="forward", ending=("1", "start")
)
label(m, "P5 repeat/volta/chords/tempo")
direction(m, rehearsal("D"), staff=1)
direction(m, metronome("quarter", 120), staff=1, sound={"tempo": 120})
direction(m, words("Allegro", font_weight="bold"), staff=1)
harmony(m, "A", "major")
note(m, "A", 5)
harmony(m, "D", "major")
note(m, "B", 5)
harmony(m, "E", "dominant")
note(m, "C", 6, alter=1)
note(m, "D", 6, dur=E, type_="eighth")
backup(m, B78)
note(m, "A", 2, dur=1260, type_="quarter", dots=1, voice=5, staff=2)
note(m, "D", 3, voice=5, staff=2)
note(m, "E", 3, voice=5, staff=2)
barline(
    m, location="right", style="light-heavy", repeat="backward", ending=("1", "stop")
)

# ---------------------------------------------------------------- bar 6
# VOLTA 2 + ornaments, grace, tremolo, notehead, pedal, 8va
m = measure(part, 6)
barline(m, location="left", ending=("2", "start"))
label(m, "P6 volta 2 + ornaments/pedal/8va")
direction(m, pedal("start"), staff=2, placement="below")
direction(m, octave_shift("down"), staff=1)
note(m, "B", 5, type_="eighth", grace={"slash": "yes"})
note(m, "C", 6, alter=1, orn=["trill-mark", ("wavy-line", {"type": "start"})])
note(m, "D", 6, orn=[("wavy-line", {"type": "stop"}), "mordent"])
note(m, "E", 6, notehead="diamond")
note(m, "F", 6, alter=1, dur=E, type_="eighth", tremolo=("single", 3))
direction(m, octave_shift("stop"), staff=1)
direction(m, pedal("stop"), staff=2, placement="below")
backup(m, B78)
note(m, "A", 2, dur=1260, type_="quarter", dots=1, voice=5, staff=2)
note(m, "E", 3, voice=5, staff=2)
note(m, "A", 3, voice=5, staff=2)
barline(m, location="right", ending=("2", "discontinue"))

# ---------------------------------------------------------------- bar 7
# two voices per staff, fermata, rit. with dashed line
m = measure(part, 7)
label(m, "P7 two voices per staff + rit.")
direction(m, words("rit.", font_style="italic"), staff=1)
direction(m, dashes("start"), staff=1)
note(m, "A", 5, dur=H, type_="half", stem="up")
note(m, "B", 5, dur=1260, type_="quarter", dots=1, stem="up", fermata=True)
backup(m, B78)
note(m, "C", 5, alter=1, voice=2, stem="down")
note(m, "D", 5, voice=2, stem="down")
note(m, "E", 5, voice=2, stem="down")
note(m, "F", 5, alter=1, dur=E, type_="eighth", voice=2, stem="down")
backup(m, B78)
note(m, "A", 2, dur=H, type_="half", voice=5, staff=2, stem="up")
note(m, "E", 3, dur=1260, type_="quarter", dots=1, voice=5, staff=2, stem="up")
backup(m, B78)
note(m, "A", 3, dur=H, type_="half", voice=6, staff=2, stem="down")
note(
    m, "C", 4, alter=1, dur=1260, type_="quarter", dots=1, voice=6, staff=2, stem="down"
)

# ---------------------------------------------------------------- bar 8
# METER CHANGE to 4/4 (last bar, so any damage is contained), arpeggios,
# fermata, final barline
m = measure(part, 8)
attributes(m, time=("4", "4"))
label(m, "P8 METER CHANGE 4/4 + arpeggios")
direction(m, dashes("stop"), staff=1)
for i, (st, oc, al) in enumerate([("A", 4, None), ("C", 5, 1), ("E", 5, None)]):
    note(m, st, oc, alter=al, dur=H, type_="half", chord=(i > 0), arpeggiate=True)
for i, (st, oc, al) in enumerate([("A", 4, None), ("D", 5, None), ("F", 5, 1)]):
    note(
        m,
        st,
        oc,
        alter=al,
        dur=H,
        type_="half",
        chord=(i > 0),
        arpeggiate="non",
        fermata=(i == 2),
    )
backup(m, B44)
for i, (st, oc) in enumerate([("A", 2), ("E", 3)]):
    note(m, st, oc, dur=H, type_="half", voice=5, staff=2, chord=(i > 0))
for i, (st, oc) in enumerate([("D", 2), ("A", 2)]):
    note(
        m,
        st,
        oc,
        dur=H,
        type_="half",
        voice=5,
        staff=2,
        chord=(i > 0),
        fermata=(i == 1),
    )
barline(m, style="light-heavy")

out = sys.argv[1] if len(sys.argv) > 1 else "paste_fragment.musicxml"
write(root, out)
expected = {n: B78 for n in range(1, 8)}
expected[8] = B44
print(f"wrote {out} | bad measure lengths: {check_lengths(out, expected)}")  # noqa: T201
