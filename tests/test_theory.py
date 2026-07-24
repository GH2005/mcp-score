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


class TestTpcRange:
    def test_all_produced_tpcs_in_range(self) -> None:
        """Every MIDI pitch, spelled by default, yields an in-range tpc."""
        for midi in range(0, 128):
            sp = theory.spell_midi(midi)
            assert theory.MIN_TPC <= sp["tpc"] <= theory.MAX_TPC
