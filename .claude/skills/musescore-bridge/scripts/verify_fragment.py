"""Verify a hand-written MusicXML file before a human ever sees it.

Three checks, in increasing strength:

1. structure    -- <note> child order, per-measure fill, no negative positions
2. import       -- MuseScore's own converter accepts it (exit 0, no corruption)
3. round-trip   -- convert back out and diff feature counts against the source

Usage
-----
    python verify_fragment.py FILE.musicxml
    python verify_fragment.py FILE.musicxml --expect 2940x7,3360
    python verify_fragment.py FILE.musicxml --against LIVE.musicxml --from-measure 21

--expect     comma list of per-measure divisions; NxM repeats N M times.
             Omit to infer each measure's length from the running maximum.
--against    audit what actually landed somewhere else (e.g. after a paste):
             compares FILE's features against LIVE's from --from-measure on.

Exit code is non-zero if any check fails, so this can gate a handoff.
"""

import argparse
import collections
import os
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET

# MusicXML schema order for the children of <note>.
NOTE_ORDER = [
    "grace",
    "chord",
    "pitch",
    "unpitched",
    "rest",
    "duration",
    "tie",
    "instrument",
    "footnote",
    "level",
    "voice",
    "type",
    "dot",
    "accidental",
    "time-modification",
    "stem",
    "notehead",
    "notehead-text",
    "staff",
    "beam",
    "notations",
    "lyric",
    "play",
    "listen",
]

FEATURES = {
    "slur": ".//slur",
    "tie": ".//tied",
    "tuplet bracket": ".//tuplet",
    "glissando": ".//glissando",
    "trill": ".//trill-mark",
    "wavy line": ".//wavy-line",
    "turn": ".//turn",
    "delayed turn": ".//delayed-turn",
    "mordent": ".//mordent",
    "inverted mordent": ".//inverted-mordent",
    "detached legato": ".//detached-legato",
    "tremolo": ".//tremolo",
    "staccato": ".//staccato",
    "accent": ".//accent",
    "tenuto": ".//tenuto",
    "marcato": ".//strong-accent",
    "staccatissimo": ".//staccatissimo",
    "breath mark": ".//breath-mark",
    "caesura": ".//caesura",
    "fingering": ".//fingering",
    "fermata": ".//fermata",
    "arpeggio": ".//arpeggiate",
    "non-arpeggiate": ".//non-arpeggiate",
    "notehead": ".//notehead",
    "grace note": ".//grace",
    "accidental": ".//accidental",
    "time-modification": ".//time-modification",
    "text (words)": ".//words",
    "dynamics": ".//dynamics",
    "hairpin": ".//wedge",
    "pedal": ".//pedal",
    "octave shift": ".//octave-shift",
    "metronome": ".//metronome",
    "rehearsal mark": ".//rehearsal",
    "segno": ".//segno",
    "coda": ".//coda",
    "dashed line": ".//dashes",
    "chord symbol": ".//harmony",
    "barline style": ".//bar-style",
    "repeat": ".//repeat",
    "volta": ".//ending",
    "clef": ".//clef",
    "key signature": ".//key",
    "time signature": ".//time",
}


def musescore_exe():
    for cand in (
        os.environ.get("MUSESCORE_EXE"),
        r"C:\Program Files\MuseScore 4\bin\MuseScore4.exe",
        shutil.which("MuseScore4"),
        shutil.which("mscore"),
    ):
        if cand and os.path.exists(cand):
            return cand
    return None


def parse_expect(spec):
    out = []
    for chunk in (spec or "").split(","):
        if not chunk:
            continue
        if "x" in chunk:
            val, times = chunk.split("x")
            out += [int(val)] * int(times)
        else:
            out.append(int(chunk))
    return out


def check_structure(path, expect):
    part = ET.parse(path).getroot().find("part")
    problems = []
    for i, m in enumerate(part.findall("measure")):
        mn = m.get("number")
        pos = hi = 0
        for e in m:
            if e.tag == "backup":
                pos -= int(e.find("duration").text)
            elif e.tag == "forward":
                pos += int(e.find("duration").text)
            elif e.tag == "note":
                idx = [NOTE_ORDER.index(c.tag) for c in e if c.tag in NOTE_ORDER]
                if idx != sorted(idx):
                    problems.append(
                        f"bar {mn}: <note> children out of schema order: "
                        + ",".join(c.tag for c in e)
                    )
                if e.find("grace") is None and e.find("chord") is None:
                    dur = e.find("duration")
                    if dur is None:
                        problems.append(f"bar {mn}: non-grace note without <duration>")
                    else:
                        pos += int(dur.text)
            if pos < 0:
                problems.append(f"bar {mn}: position went negative (backup too large)")
            hi = max(hi, pos)
        if expect:
            want = expect[i] if i < len(expect) else expect[-1]
            if hi != want:
                problems.append(f"bar {mn}: fills {hi} divisions, expected {want}")
    return problems


def convert(exe, src, dst):
    r = subprocess.run([exe, "-o", dst, src], capture_output=True, text=True)
    return r.returncode


def scan(path, from_measure=None, skip_opening_attributes=False):
    part = ET.parse(path).getroot().find("part")
    ms = [
        m
        for m in part.findall("measure")
        if from_measure is None or int(m.get("number")) >= from_measure
    ]
    out = {}
    for name, xp in FEATURES.items():
        out[name] = sum(len(m.findall(xp)) for m in ms)
    if skip_opening_attributes and ms:
        # A fragment's first <attributes> states the clef/key/meter it starts
        # in. Those are not *changes* and are not expected to travel in a
        # paste, so counting them as losses would be misleading.
        opening = ms[0].find("attributes")
        if opening is not None:
            for name, tag in (
                ("clef", "clef"),
                ("key signature", "key"),
                ("time signature", "time"),
            ):
                out[name] = max(0, out[name] - len(opening.findall(tag)))
    vs = collections.defaultdict(collections.Counter)
    for m in ms:
        for n in m.findall(".//note"):
            v, s = n.find("voice"), n.find("staff")
            if v is not None and s is not None:
                vs[v.text][s.text] += 1
    out["voices"] = len(vs)
    out["cross-staff notes"] = sum(
        sum(c.values()) - c.most_common(1)[0][1] for c in vs.values()
    )
    return out


def report_diff(a, b, left="sent", right="landed"):
    print(f"\n{'feature':24s} {left:>7s} {right:>8s}   verdict")  # noqa: T201
    print("-" * 56)  # noqa: T201
    lost = []
    for k in a:
        if a[k] == 0 and b[k] == 0:
            continue
        if b[k] >= a[k]:
            verdict = "OK"
        elif b[k] == 0:
            verdict = "LOST"
            lost.append(k)
        else:
            verdict = f"partial {b[k]}/{a[k]}"
            lost.append(k)
        print(f"{k:24s} {a[k]:7d} {b[k]:8d}   {verdict}")  # noqa: T201
    return lost


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("file")
    ap.add_argument("--expect", default=None)
    ap.add_argument("--against", default=None)
    ap.add_argument("--from-measure", type=int, default=1)
    args = ap.parse_args()

    failed = False

    print("== structure")  # noqa: T201
    problems = check_structure(args.file, parse_expect(args.expect))
    if problems:
        failed = True
        for p in problems[:20]:
            print("   FAIL", p)  # noqa: T201
    else:
        print("   ok: schema order, measure fills, no negative positions")  # noqa: T201

    if args.against:
        print(f"\n== landed audit ({args.against}, from bar {args.from_measure})")  # noqa: T201
        print(  # noqa: T201
            "   (the fragment's opening clef/key/meter are excluded: they "
            "state where it starts, they are not changes)"
        )
        lost = report_diff(
            scan(args.file, skip_opening_attributes=True),
            scan(args.against, args.from_measure),
        )
        if lost:
            print(  # noqa: T201
                "\n   note: these did not survive -- hand the user a checklist:",
                ", ".join(lost),
            )
        return 1 if failed else 0

    exe = musescore_exe()
    if not exe:
        print("\n== import: SKIPPED (set MUSESCORE_EXE to enable the strongest check)")  # noqa: T201
        return 1 if failed else 0

    print("\n== import (MuseScore converter)")  # noqa: T201
    tmp_rt = args.file.replace(".musicxml", "") + ".__rt.musicxml"
    rc = convert(exe, args.file, tmp_rt)
    if rc != 0:
        failed = True
        print(  # noqa: T201
            f"   FAIL exit {rc} -- read the newest log in "
            r"%LOCALAPPDATA%\MuseScore\MuseScore4\logs for the reason"
        )
    else:
        print("   ok: exit 0, no corruption reported")  # noqa: T201
        print("\n== round-trip")  # noqa: T201
        lost = report_diff(scan(args.file), scan(tmp_rt), "written", "read back")
        if lost:
            print("\n   downgraded by the importer:", ", ".join(lost))  # noqa: T201
        os.remove(tmp_rt)

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
