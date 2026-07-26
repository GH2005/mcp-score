"""Tests for the music21-backed theory helpers.

These are pure-Python (no bridge, no MuseScore): spelling round-trips,
key-aware MIDI spelling, roman/chord-symbol realization, and enharmonic
transposition. The MuseScore tpc convention under test is F=13, C=14,
Cb=7, Db=9, Eb=11, Bb=12, C#=21 (verified against the plugin's apiProbe).
"""

from __future__ import annotations

import pytest

from mcp_score import theory


class TestNameToPitchTpc:
    @pytest.mark.parametrize(
        ("name", "midi", "tpc"),
        [
            ("C4", 60, 14),
            ("C#4", 61, 21),
            ("D-4", 61, 9),  # music21 flat spelling
            ("Db4", 61, 9),  # human flat spelling
            ("E-3", 51, 11),
            ("Bb2", 46, 12),
            ("Cb4", 59, 7),
            ("G#5", 80, 22),
        ],
    )
    def test_known_pitches(self, name: str, midi: int, tpc: int) -> None:
        result = theory.name_to_pitch_tpc(name)
        assert result["midi"] == midi
        assert result["tpc"] == tpc

    def test_flat_and_sharp_stay_distinct(self) -> None:
        """Db and C# are the same MIDI but must not collapse to one tpc."""
        flat = theory.name_to_pitch_tpc("Db4")
        sharp = theory.name_to_pitch_tpc("C#4")
        assert flat["midi"] == sharp["midi"] == 61
        assert flat["tpc"] != sharp["tpc"]

    def test_display_uses_b_for_flats(self) -> None:
        assert theory.name_to_pitch_tpc("E-4")["display"] == "Eb4"
        assert theory.name_to_pitch_tpc("E-4")["name"] == "E-4"

    def test_missing_octave_rejected(self) -> None:
        with pytest.raises(ValueError, match="octave"):
            theory.name_to_pitch_tpc("D-")

    def test_garbage_rejected(self) -> None:
        with pytest.raises(ValueError, match="unparseable"):
            theory.name_to_pitch_tpc("H4")


class TestPitchTpcToName:
    @pytest.mark.parametrize(
        ("midi", "tpc"),
        [(60, 14), (61, 9), (61, 21), (63, 11), (70, 12), (59, 7), (43, 15)],
    )
    def test_roundtrip(self, midi: int, tpc: int) -> None:
        """(midi, tpc) -> name -> (midi, tpc) is the identity."""
        spelled = theory.pitch_tpc_to_name(midi, tpc)
        assert spelled["midi"] == midi
        assert spelled["tpc"] == tpc

    def test_name_to_pitch_inverts(self) -> None:
        for name in ("Db4", "C#4", "Eb3", "Cb4", "F#2"):
            sp = theory.name_to_pitch_tpc(name)
            back = theory.pitch_tpc_to_name(sp["midi"], sp["tpc"])
            assert back["display"] == name.replace("-", "b")


class TestSpellMidi:
    def test_no_context_uses_default(self) -> None:
        assert theory.spell_midi(61)["display"] == "C#4"

    def test_flat_key_spells_flat(self) -> None:
        """MIDI 68 in E-flat major is A-flat, not G-sharp."""
        assert theory.spell_midi(68, "E-")["display"] == "Ab4"

    def test_diatonic_pitch_unchanged(self) -> None:
        assert theory.spell_midi(63, "E-")["display"] == "Eb4"

    def test_out_of_range_rejected(self) -> None:
        with pytest.raises(ValueError, match="0..127"):
            theory.spell_midi(200)


class TestRealize:
    def test_roman_numeral(self) -> None:
        names = [p["display"] for p in theory.realize("V7/V", "E-", octave=4)]
        assert names == ["F4", "A4", "C5", "Eb5"]

    def test_chord_symbol(self) -> None:
        names = [p["display"] for p in theory.realize("E-maj7", "C", octave=3)]
        assert names == ["Eb3", "G3", "Bb3", "D4"]

    def test_augmented_sixth_spelling(self) -> None:
        """A German augmented sixth spells D-sharp, not E-flat."""
        names = [p["display"] for p in theory.realize("Ger65", "a", octave=3)]
        assert "D#4" in names
        assert "Eb4" not in names

    def test_octave_anchor(self) -> None:
        low = theory.realize("I", "C", octave=2)
        assert low[0]["display"] == "C2"

    def test_flat_root_convention(self) -> None:
        """'B-7' is B-flat dominant 7, not B with a flat-7 extension."""
        names = [p["display"] for p in theory.realize("B-7", "C", octave=3)]
        assert names[0] == "Bb3"

    def test_unparseable_rejected(self) -> None:
        with pytest.raises(ValueError, match="could not parse"):
            theory.realize("not-a-chord", "C")


class TestTransposePitchTpc:
    @pytest.mark.parametrize(
        ("midi", "tpc", "semitones", "expected"),
        [
            (60, 14, 2, (62, 16)),  # C -> D
            (60, 14, 1, (61, 21)),  # C -> C# (ascending chromatic)
            (61, 9, -1, (60, 14)),  # Db -> C
            (67, 15, 5, (72, 14)),  # G -> C
            (60, 14, 12, (72, 14)),  # octave up, spelling preserved
        ],
    )
    def test_transpose(
        self, midi: int, tpc: int, semitones: int, expected: tuple[int, int]
    ) -> None:
        assert theory.transpose_pitch_tpc(midi, tpc, semitones) == expected


class TestMidiRangeIsNotSilentlyWrapped:
    """music21 folds an out-of-range pitch back into 0..127 by octaves.

    Left unguarded that turns "transpose off the top of the range" into
    "write a note several octaves lower", which reads as success. Every
    planner must see the true value and refuse.
    """

    def test_chromatic_transposition_reports_the_out_of_range_pitch(self) -> None:
        new_midi, _ = theory.transpose_pitch_tpc(127, 15, 12)

        assert new_midi == 139

    def test_chromatic_plan_refuses_instead_of_dropping_an_octave(self) -> None:
        snapshot = _snapshot([{"events": [_event(0, 4, ["G9"])]}])

        result = theory.plan_transposition(snapshot, 0, 1, 1, 12)

        assert isinstance(result, str)
        assert "MIDI range" in result

    def test_diatonic_plan_refuses(self) -> None:
        snapshot = _snapshot([{"events": [_event(0, 4, ["G9"])]}])

        result = theory.plan_diatonic_transposition(snapshot, 0, 1, 1, 6, "C")

        assert isinstance(result, str)
        assert "MIDI range" in result


class TestTpcRange:
    def test_all_produced_tpcs_in_range(self) -> None:
        """Every MIDI pitch, spelled by default, yields an in-range tpc."""
        for midi in range(0, 128):
            sp = theory.spell_midi(midi)
            assert theory.MIN_TPC <= sp["tpc"] <= theory.MAX_TPC


# ── Write intelligence: voicing, diatonic motion, transformations ────


def _event(
    offset: float,
    ql: float,
    names: list[str] | None = None,
    voice: str | None = None,
    tie: str | None = None,
) -> dict[str, object]:
    """One snapshot event, shaped the way musicxml.parse_snapshot emits it."""
    from music21 import pitch

    entry: dict[str, object] = {"offset": offset, "ql": ql}
    if names:
        entry["kind"] = "chord" if len(names) > 1 else "note"
        entry["names"] = sorted(names)
        entry["midi"] = sorted(pitch.Pitch(n).midi for n in names)
    else:
        entry["kind"] = "rest"
    if voice is not None:
        entry["voice"] = voice
    if tie is not None:
        entry["tie"] = tie
    return entry


def _snapshot(
    measures: list[dict[str, object]], measure_count: int | None = None
) -> dict[str, object]:
    """A one-staff snapshot built from measure dicts, 1-indexed."""
    return {
        "title": "fixture",
        "measure_count": measure_count or len(measures),
        "staves": {"0": {str(i + 1): m for i, m in enumerate(measures)}},
    }


def _spellings(plans: list[dict[str, object]]) -> list[str]:
    """The display names a plan's edits would write, in plan order."""
    names: list[str] = []
    for plan in plans:
        for edit in plan["edits"]:
            names.append(
                theory.pitch_tpc_to_name(edit["newPitch"], edit["newTpc"])["display"]
            )
    return names


class TestRealizeDetailed:
    """realize_detailed: the pitches, plus what the figure means."""

    def test_secondary_dominant_reports_the_key_it_tonicizes(self) -> None:
        pitches, metadata = theory.realize_detailed("V7/V", "E-")

        assert [p["display"] for p in pitches] == ["F4", "A4", "C5", "Eb5"]
        assert metadata["parsed_as"] == "roman"
        assert metadata["root"] == "F"
        assert metadata["secondary_key"] == "B- major"

    def test_inverted_roman_reports_bass_and_inversion(self) -> None:
        _, metadata = theory.realize_detailed("ii65", "C")

        assert metadata["inversion"] == 1
        assert metadata["bass"] == "F"
        assert metadata["inversion_name"] == "65"

    def test_chord_symbol_metadata(self) -> None:
        _, metadata = theory.realize_detailed("E-maj7", "C")

        assert metadata["parsed_as"] == "chord_symbol"
        assert metadata["root"] == "Eb"
        assert metadata["secondary_key"] is None

    def test_realize_still_returns_only_pitches(self) -> None:
        """The old entry point is unchanged for every existing caller."""
        assert theory.realize("V7", "C") == theory.realize_detailed("V7", "C")[0]


class TestPlanProgressionVoicing:
    """plan_progression_voicing: figures become independent parts."""

    def test_registered_bass_octave_yields_solutions(self) -> None:
        """Regression guard: unless every element's bass carries an
        octave, the solver silently returns zero solutions."""
        result = theory.plan_progression_voicing(["I", "IV", "V7", "I"], "C")

        assert result["solution_count"] > 0
        assert len(result["chords"]) == 4

    def test_pitches_are_bass_first(self) -> None:
        """music21 hands back a possibility top-down; we publish bass-up."""
        result = theory.plan_progression_voicing(["I", "IV", "V7", "I"], "C")

        for voiced in result["chords"]:
            midis = [p["midi"] for p in voiced["pitches"]]
            assert midis[0] == min(midis)

    def test_first_progression_matches_full_enumeration(self) -> None:
        """Guards the private-attribute walk against a music21 upgrade."""
        from music21 import key, pitch

        realization = theory._realize_progression(
            ["I", "IV", "V7", "I"], key.Key("C"), 4, 3, "B5", []
        )
        greedy = theory._first_progression(realization)

        assert list(greedy) == list(realization.getAllPossibilityProgressions()[0])
        assert all(isinstance(p, pitch.Pitch) for poss in greedy for p in poss)

    def test_chord_symbol_figures_accepted(self) -> None:
        result = theory.plan_progression_voicing(["Dm7", "G7", "Cmaj7"], "C")

        assert result["solution_count"] > 0
        assert [c["figure"] for c in result["chords"]] == ["Dm7", "G7", "Cmaj7"]

    def test_spells_for_the_key(self) -> None:
        result = theory.plan_progression_voicing(["I", "ii65", "V7", "I"], "E-")

        written = [p["display"] for c in result["chords"] for p in c["pitches"]]
        assert any(n.startswith("Eb") for n in written)
        assert not any("#" in n for n in written)

    def test_deterministic_across_calls(self) -> None:
        first = theory.plan_progression_voicing(["I", "vi", "ii", "V"], "C")
        second = theory.plan_progression_voicing(["I", "vi", "ii", "V"], "C")

        assert first == second

    def test_three_parts_supported(self) -> None:
        result = theory.plan_progression_voicing(["I", "V", "I"], "C", num_parts=3)

        assert all(len(c["pitches"]) == 3 for c in result["chords"])

    def test_relaxations_are_applied(self) -> None:
        """A relaxed rule can only ever widen the search."""
        strict = theory.plan_progression_voicing(["I", "IV", "V7", "I"], "C")
        relaxed = theory.plan_progression_voicing(
            ["I", "IV", "V7", "I"], "C", relax=["forbidVoiceCrossing"]
        )

        assert relaxed["solution_count"] >= strict["solution_count"]

    def test_every_relaxable_rule_exists_on_music21(self) -> None:
        """The whitelist must not drift from music21's Rules object."""
        from music21.figuredBass import rules

        fb_rules = rules.Rules()
        for name in theory.RELAXABLE_RULES:
            assert hasattr(fb_rules, name), name

    def test_unknown_rule_rejected(self) -> None:
        with pytest.raises(ValueError, match="unknown rule"):
            theory.plan_progression_voicing(["I"], "C", relax=["forbidBadTaste"])

    def test_unparseable_figure_rejected(self) -> None:
        with pytest.raises(ValueError, match="could not parse"):
            theory.plan_progression_voicing(["I", "Zz9"], "C")

    def test_unparseable_key_rejected(self) -> None:
        with pytest.raises(ValueError, match="unparseable key"):
            theory.plan_progression_voicing(["I"], "H")


class TestPlanDiatonicTransposition:
    """plan_diatonic_transposition: move within the key, not across it."""

    def test_stays_in_key_where_a_generic_interval_would_not(self) -> None:
        """In E-flat, up a third from C is E-flat, not E natural. This is
        exactly the case music21's GenericInterval gets wrong."""
        snapshot = _snapshot(
            [{"events": [_event(0, 1, ["C5"]), _event(1, 1, ["A-4"])]}]
        )

        result = theory.plan_diatonic_transposition(snapshot, 0, 1, 1, 2, "E-")

        assert _spellings(result["plans"]) == ["Eb5", "C5"]

    def test_descending_degrees(self) -> None:
        snapshot = _snapshot([{"events": [_event(0, 1, ["C5"])]}])

        result = theory.plan_diatonic_transposition(snapshot, 0, 1, 1, -3, "E-")

        assert _spellings(result["plans"]) == ["G4"]

    def test_chromatic_note_snaps_and_is_reported(self) -> None:
        snapshot = _snapshot([{"events": [_event(0, 1, ["E4"])]}])

        result = theory.plan_diatonic_transposition(snapshot, 0, 1, 1, 1, "E-")

        assert _spellings(result["plans"]) == ["F4"]
        assert result["snapped"] == [{"measure": 1, "from": "E4", "to": "F4"}]

    def test_in_key_notes_are_not_reported_as_snapped(self) -> None:
        snapshot = _snapshot([{"events": [_event(0, 1, ["G4"])]}])

        result = theory.plan_diatonic_transposition(snapshot, 0, 1, 1, 1, "E-")

        assert result["snapped"] == []

    def test_minor_key_is_natural_minor(self) -> None:
        snapshot = _snapshot([{"events": [_event(0, 1, ["G4"])]}])

        result = theory.plan_diatonic_transposition(snapshot, 0, 1, 1, 1, "c")

        assert _spellings(result["plans"]) == ["Ab4"]

    def test_zero_degrees_rejected(self) -> None:
        snapshot = _snapshot([{"events": [_event(0, 1, ["C4"])]}])

        assert isinstance(
            theory.plan_diatonic_transposition(snapshot, 0, 1, 1, 0, "C"), str
        )

    def test_unparseable_key_rejected(self) -> None:
        snapshot = _snapshot([{"events": [_event(0, 1, ["C4"])]}])

        result = theory.plan_diatonic_transposition(snapshot, 0, 1, 1, 1, "H")

        assert isinstance(result, str)
        assert "unparseable key" in result

    def test_leaving_the_midi_range_refuses_the_whole_plan(self) -> None:
        snapshot = _snapshot([{"events": [_event(0, 1, ["C4"]), _event(1, 1, ["G9"])]}])

        result = theory.plan_diatonic_transposition(snapshot, 0, 1, 1, 6, "C")

        assert isinstance(result, str)
        assert "MIDI range" in result

    def test_voice_filter(self) -> None:
        snapshot = _snapshot(
            [
                {
                    "events": [
                        _event(0, 1, ["C4"], voice="1"),
                        _event(0, 1, ["C5"], voice="2"),
                    ]
                }
            ]
        )

        result = theory.plan_diatonic_transposition(snapshot, 0, 1, 1, 1, "C", voice=1)

        assert [p["voice"] for p in result["plans"]] == [1]


class TestPlanInversion:
    """plan_inversion: mirror the line, keep the key."""

    def test_reflects_letters_around_the_axis(self) -> None:
        snapshot = _snapshot(
            [
                {
                    "events": [
                        _event(0, 1, ["C4"]),
                        _event(1, 1, ["E4"]),
                        _event(2, 1, ["G4"]),
                        _event(3, 1, ["C5"]),
                    ]
                }
            ]
        )

        result = theory.plan_inversion(snapshot, 0, 1, 1, "G4", "C")

        assert _spellings(result["plans"]) == ["D5", "B4", "G4", "D4"]

    def test_key_signature_supplies_the_accidentals(self) -> None:
        snapshot = _snapshot([{"events": [_event(0, 4, ["B-4"])]}])

        result = theory.plan_inversion(snapshot, 0, 1, 1, "G4", "E-")

        assert _spellings(result["plans"]) == ["Eb4"]

    def test_chromatic_inflection_is_dropped_and_reported(self) -> None:
        snapshot = _snapshot([{"events": [_event(0, 4, ["F#4"])]}])

        result = theory.plan_inversion(snapshot, 0, 1, 1, "C4", "C")

        assert _spellings(result["plans"]) == ["G3"]
        assert len(result["snapped"]) == 1
        assert result["snapped"][0]["from"] == "F#4"

    def test_axis_needs_an_octave(self) -> None:
        snapshot = _snapshot([{"events": [_event(0, 1, ["C4"])]}])

        result = theory.plan_inversion(snapshot, 0, 1, 1, "G", "C")

        assert isinstance(result, str)
        assert "octave" in result

    def test_plans_are_setpitches_shaped(self) -> None:
        snapshot = _snapshot([{"events": [_event(0, 4, ["C4"])]}])

        result = theory.plan_inversion(snapshot, 0, 1, 1, "G4", "C")

        edit = result["plans"][0]["edits"][0]
        assert set(edit) == {"oldPitch", "newPitch", "newTpc"}


class TestPlanRetrograde:
    """plan_retrograde: backwards in pitch and in rhythm."""

    def test_reverses_pitches_and_durations(self) -> None:
        snapshot = _snapshot(
            [
                {
                    "events": [
                        _event(0, 1, ["C4"]),
                        _event(1, 1, ["D4"]),
                        _event(2, 2, ["E4"]),
                    ]
                }
            ]
        )

        result = theory.plan_retrograde(snapshot, 0, 1, 1, 0)

        assert result["entries"] == [
            {"numerator": 1, "denominator": 2, "name": "E4"},
            {"numerator": 1, "denominator": 4, "name": "D4"},
            {"numerator": 1, "denominator": 4, "name": "C4"},
        ]

    def test_chords_and_rests_survive_the_reversal(self) -> None:
        snapshot = _snapshot(
            [{"events": [_event(0, 2, ["C4", "E4", "G4"]), _event(2, 2, None)]}]
        )

        result = theory.plan_retrograde(snapshot, 0, 1, 1, 0)

        assert result["entries"][0]["rest"] is True
        assert result["entries"][1]["chord"] == ["C4", "E4", "G4"]

    def test_refuses_a_tied_passage(self) -> None:
        snapshot = _snapshot(
            [
                {
                    "events": [
                        _event(0, 1, ["C4"], tie="start"),
                        _event(1, 3, ["C4"], tie="stop"),
                    ]
                }
            ]
        )

        result = theory.plan_retrograde(snapshot, 0, 1, 1, 0)

        assert isinstance(result, str)
        assert "tie" in result

    def test_refuses_tuplets(self) -> None:
        snapshot = _snapshot(
            [
                {
                    "events": [
                        _event(0, 0.3333, ["C4"]),
                        _event(0.3333, 0.3333, ["D4"]),
                        _event(0.6667, 0.3333, ["E4"]),
                        _event(1, 3, ["F4"]),
                    ]
                }
            ]
        )

        result = theory.plan_retrograde(snapshot, 0, 1, 1, 0)

        assert isinstance(result, str)
        assert "tuplet" in result

    def test_refuses_a_gapped_voice(self) -> None:
        snapshot = _snapshot([{"events": [_event(0, 1, ["C4"]), _event(2, 1, ["D4"])]}])

        result = theory.plan_retrograde(snapshot, 0, 1, 1, 0)

        assert isinstance(result, str)
        assert "gap" in result

    def test_refuses_an_empty_voice(self) -> None:
        snapshot = _snapshot([{"events": [_event(0, 4, ["C4"], voice="1")]}])

        result = theory.plan_retrograde(snapshot, 0, 1, 1, 2)

        assert isinstance(result, str)
        assert "voice 2" in result

    def test_refuses_a_meter_change_inside_the_range(self) -> None:
        snapshot = _snapshot(
            [
                {"events": [_event(0, 4, ["C4"])]},
                {"events": [_event(0, 3, ["D4"])], "time": ["3/4"]},
            ]
        )

        result = theory.plan_retrograde(snapshot, 0, 1, 2, 0)

        assert isinstance(result, str)
        assert "time signature" in result

    def test_refuses_uneven_bars(self) -> None:
        snapshot = _snapshot(
            [
                {"events": [_event(0, 4, ["C4"])]},
                {"events": [_event(0, 2, ["D4"])]},
            ]
        )

        result = theory.plan_retrograde(snapshot, 0, 1, 2, 0)

        assert isinstance(result, str)
        assert "full bars" in result

    def test_dotted_durations_survive(self) -> None:
        snapshot = _snapshot([{"events": [_event(0, 3, ["C4"]), _event(3, 1, ["D4"])]}])

        result = theory.plan_retrograde(snapshot, 0, 1, 1, 0)

        assert result["entries"][1] == {
            "numerator": 3,
            "denominator": 4,
            "name": "C4",
        }


class TestPlanSequence:
    """plan_sequence: the motif again, a step higher each time."""

    @staticmethod
    def _motif_snapshot(measure_count: int = 3) -> dict[str, object]:
        empty = {"events": [_event(0, 4, None)]}
        return _snapshot(
            [
                {
                    "events": [
                        _event(0, 1, ["C4"]),
                        _event(1, 1, ["E4"]),
                        _event(2, 1, ["G4"]),
                        _event(3, 1, ["C5"]),
                    ]
                },
                *([empty] * (measure_count - 1)),
            ],
            measure_count,
        )

    def test_copies_land_one_motif_length_apart(self) -> None:
        result = theory.plan_sequence(self._motif_snapshot(), 0, 1, 1, 2, 1, "C", 0)

        assert [c["measure"] for c in result["copies"]] == [2, 3]
        assert result["destination_end"] == 3

    def test_shift_accumulates_per_copy(self) -> None:
        result = theory.plan_sequence(self._motif_snapshot(), 0, 1, 1, 2, 1, "C", 0)

        assert [e["name"] for e in result["copies"][0]["entries"]] == [
            "D4",
            "F4",
            "A4",
            "D5",
        ]
        assert [e["name"] for e in result["copies"][1]["entries"]] == [
            "E4",
            "G4",
            "B4",
            "E5",
        ]

    def test_zero_degrees_repeats_verbatim(self) -> None:
        result = theory.plan_sequence(self._motif_snapshot(), 0, 1, 1, 1, 0, "C", 0)

        assert [e["name"] for e in result["copies"][0]["entries"]] == [
            "C4",
            "E4",
            "G4",
            "C5",
        ]

    def test_refuses_and_names_the_measures_needed(self) -> None:
        result = theory.plan_sequence(self._motif_snapshot(), 0, 1, 1, 5, 1, "C", 0)

        assert isinstance(result, str)
        assert "append_live_measures(3)" in result

    def test_copies_must_be_positive(self) -> None:
        assert isinstance(
            theory.plan_sequence(self._motif_snapshot(), 0, 1, 1, 0, 1, "C", 0), str
        )

    def test_unparseable_key_rejected(self) -> None:
        result = theory.plan_sequence(self._motif_snapshot(), 0, 1, 1, 1, 1, "H", 0)

        assert isinstance(result, str)
        assert "unparseable key" in result


class TestRealizeOrnamentNotes:
    """realize_ornament_notes: the symbol written out as notes."""

    def test_trill_fills_the_source_duration(self) -> None:
        written = theory.realize_ornament_notes("trill", "C5", 1, 4, "D")

        assert [n["display"] for n in written] == ["C5", "D5"] * 4
        assert all(n["denominator"] == 32 for n in written)

    def test_durations_sum_to_the_source_exactly(self) -> None:
        from fractions import Fraction

        for ornament in theory.ORNAMENTS:
            written = theory.realize_ornament_notes(ornament, "C5", 1, 4, "C")
            total = sum(Fraction(n["numerator"], n["denominator"]) for n in written)
            assert total == Fraction(1, 4), ornament

    def test_auxiliary_notes_follow_the_key(self) -> None:
        """In E-flat the note below C is B-flat, not B natural."""
        written = theory.realize_ornament_notes("mordent", "C5", 1, 4, "E-")

        assert [n["display"] for n in written] == ["C5", "Bb4", "C5"]

    def test_inverted_variants_supported(self) -> None:
        written = theory.realize_ornament_notes("inverted_mordent", "C5", 1, 4, "C")

        assert [n["display"] for n in written] == ["C5", "D5", "C5"]

    def test_unknown_ornament_rejected(self) -> None:
        with pytest.raises(ValueError, match="unknown ornament"):
            theory.realize_ornament_notes("wobble", "C5", 1, 4, "C")

    def test_tuplet_denominator_rejected(self) -> None:
        with pytest.raises(ValueError, match="tuplet"):
            theory.realize_ornament_notes("trill", "C5", 1, 3, "C")

    def test_note_needs_an_octave(self) -> None:
        with pytest.raises(ValueError, match="octave"):
            theory.realize_ornament_notes("trill", "C", 1, 4, "C")

    def test_unparseable_key_rejected(self) -> None:
        with pytest.raises(ValueError, match="unparseable key"):
            theory.realize_ornament_notes("trill", "C5", 1, 4, "H")
