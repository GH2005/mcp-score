"""Minimal MusicXML builder for hand-written score fragments.

Raw XML, no intermediate library, so nothing gets filtered by another tool's
idea of what is expressible. Element order follows the MusicXML schema.
"""

import xml.etree.ElementTree as ET

DIV = 840  # divisions per quarter; divisible by 3, 5, 7, 8


def new_score(title, part_name="Piano"):
    root = ET.Element("score-partwise", version="4.0")
    work = ET.SubElement(root, "work")
    ET.SubElement(work, "work-title").text = title
    ident = ET.SubElement(root, "identification")
    enc = ET.SubElement(ident, "encoding")
    ET.SubElement(enc, "software").text = "mcp-score fragment builder"
    pl = ET.SubElement(root, "part-list")
    sp = ET.SubElement(pl, "score-part", id="P1")
    ET.SubElement(sp, "part-name").text = part_name
    part = ET.SubElement(root, "part", id="P1")
    return root, part


def sub(parent, tag, text=None, **attrs):
    e = ET.SubElement(
        parent, tag, {k.replace("_", "-"): str(v) for k, v in attrs.items()}
    )
    if text is not None:
        e.text = str(text)
    return e


def measure(part, n):
    return ET.SubElement(part, "measure", number=str(n))


def attributes(m, divisions=None, fifths=None, time=None, clefs=None, staves=None):
    a = sub(m, "attributes")
    if divisions:
        sub(a, "divisions", divisions)
    if fifths is not None:
        k = sub(a, "key")
        sub(k, "fifths", fifths)
    if time:
        t = sub(a, "time")
        sub(t, "beats", time[0])
        sub(t, "beat-type", time[1])
    if staves:
        sub(a, "staves", staves)
    for num, (sign, line) in sorted((clefs or {}).items()):
        c = sub(a, "clef", number=num)
        sub(c, "sign", sign)
        sub(c, "line", line)
    return a


def direction(m, build, staff=1, placement="above", sound=None):
    d = sub(m, "direction", placement=placement)
    dt = sub(d, "direction-type")
    build(dt)
    sub(d, "staff", staff)
    if sound:
        sub(d, "sound", **sound)
    return d


def words(txt, **kw):
    return lambda dt: sub(dt, "words", txt, **kw)


def dynamic(name):
    return lambda dt: sub(sub(dt, "dynamics"), name)


def wedge(kind, number=1):
    return lambda dt: sub(dt, "wedge", type=kind, number=number)


def pedal(kind, line="yes"):
    return lambda dt: sub(dt, "pedal", type=kind, line=line)


def rehearsal(txt):
    return lambda dt: sub(dt, "rehearsal", txt)


def dashes(kind, number=1):
    return lambda dt: sub(dt, "dashes", type=kind, number=number)


def segno():
    return lambda dt: sub(dt, "segno")


def coda():
    return lambda dt: sub(dt, "coda")


def octave_shift(kind, size=8, number=1):
    return lambda dt: sub(dt, "octave-shift", type=kind, size=size, number=number)


def metronome(beat, per_minute, dots=0):
    def build(dt):
        mm = sub(dt, "metronome")
        sub(mm, "beat-unit", beat)
        for _ in range(dots):
            sub(mm, "beat-unit-dot")
        sub(mm, "per-minute", per_minute)

    return build


def harmony(m, step, kind, alter=None):
    h = sub(m, "harmony")
    r = sub(h, "root")
    sub(r, "root-step", step)
    if alter is not None:
        sub(r, "root-alter", alter)
    sub(h, "kind", kind)
    return h


def note(
    m,
    step=None,
    octave=None,
    alter=None,
    dur=DIV,
    type_="quarter",
    voice=1,
    staff=1,
    chord=False,
    dots=0,
    tie=None,
    slur=None,
    artic=(),
    orn=(),
    fingering=None,
    fermata=False,
    arpeggiate=None,
    notehead=None,
    tremolo=None,
    gliss=None,
    grace=None,
    tuplet=None,
    tmod=None,
    stem=None,
    accidental=None,
    rest=False,
    measure_rest=False,
):
    n = sub(m, "note")
    if grace is not None:
        sub(n, "grace", **grace)
    if chord:
        sub(n, "chord")
    if rest:
        r = sub(n, "rest")
        if measure_rest:
            r.set("measure", "yes")
    else:
        p = sub(n, "pitch")
        sub(p, "step", step)
        if alter is not None:
            sub(p, "alter", alter)
        sub(p, "octave", octave)
    if grace is None:
        sub(n, "duration", dur)
    for t in tie or []:
        sub(n, "tie", type=t)
    sub(n, "voice", voice)
    if type_:
        sub(n, "type", type_)
    for _ in range(dots):
        sub(n, "dot")
    if accidental:
        txt, extra = accidental
        sub(n, "accidental", txt, **extra)
    if tmod:
        tm = sub(n, "time-modification")
        sub(tm, "actual-notes", tmod[0])
        sub(tm, "normal-notes", tmod[1])
        if len(tmod) > 2:
            sub(tm, "normal-type", tmod[2])
    if stem:
        sub(n, "stem", stem)
    if notehead:
        sub(n, "notehead", notehead)
    sub(n, "staff", staff)

    if not any(
        [tie, slur, tuplet, gliss, orn, tremolo, fingering, artic, fermata, arpeggiate]
    ):
        return n
    nots = sub(n, "notations")
    for t in tie or []:
        sub(nots, "tied", type=t)
    for s in slur or []:
        sub(nots, "slur", type=s[0], number=s[1])
    if tuplet:
        sub(nots, "tuplet", type=tuplet, bracket="yes")
    if gliss:
        sub(
            nots,
            "glissando",
            gliss[1] if len(gliss) > 1 else None,
            type=gliss[0],
            number=1,
            line_type="wavy",
        )
    if orn or tremolo:
        o = sub(nots, "ornaments")
        for item in orn:
            name, kw = item if isinstance(item, tuple) else (item, {})
            sub(o, name, **kw)
        if tremolo:
            sub(o, "tremolo", tremolo[1], type=tremolo[0])
    if fingering:
        t = sub(nots, "technical")
        sub(t, "fingering", fingering)
    if artic:
        a = sub(nots, "articulations")
        for item in artic:
            name, kw = item if isinstance(item, tuple) else (item, {})
            sub(a, name, **kw)
    if fermata:
        sub(nots, "fermata", "normal", type="upright")
    if arpeggiate == "non":
        sub(nots, "non-arpeggiate", type="bottom")
    elif arpeggiate:
        sub(nots, "arpeggiate")
    return n


def backup(m, d):
    b = ET.SubElement(m, "backup")
    sub(b, "duration", d)


def barline(m, location="right", style=None, repeat=None, ending=None):
    b = sub(m, "barline", location=location)
    if style:
        sub(b, "bar-style", style)
    if ending:
        sub(
            b,
            "ending",
            ending[2] if len(ending) > 2 else None,
            number=ending[0],
            type=ending[1],
        )
    if repeat:
        sub(b, "repeat", direction=repeat)
    return b


def label(m, txt):
    direction(
        m, words(txt, font_size=8, font_style="italic"), staff=1, placement="above"
    )


def write(root, path):
    ET.indent(root, space="  ")
    with open(path, "wb") as fh:
        fh.write(b'<?xml version="1.0" encoding="UTF-8"?>\n')
        fh.write(
            b"<!DOCTYPE score-partwise PUBLIC "
            b'"-//Recordare//DTD MusicXML 4.0 Partwise//EN" '
            b'"http://www.musicxml.org/dtds/partwise.dtd">\n'
        )
        ET.ElementTree(root).write(fh, encoding="UTF-8", xml_declaration=False)


def check_lengths(path, expected):
    """expected: {measure number: divisions}. Returns list of (bar, got, want)."""
    part = ET.parse(path).getroot().find("part")
    bad = []
    for m in part.findall("measure"):
        mn = int(m.get("number"))
        pos = hi = 0
        for e in m:
            if e.tag == "backup":
                pos -= int(e.find("duration").text)
            elif (
                e.tag == "forward"
                or e.tag == "note"
                and e.find("grace") is None
                and e.find("chord") is None
            ):
                pos += int(e.find("duration").text)
            hi = max(hi, pos)
        if hi != expected[mn]:
            bad.append((mn, hi, expected[mn]))
    return bad
