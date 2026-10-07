"""Diarization-driven casting — parse_diarize / speaker_voices /
anchor_speakers regression tests (yt-voice-dub-speakers card)."""
import importlib.util
from pathlib import Path

import pytest

DUB = Path(__file__).resolve().parents[2] / "scripts/ops/yt-vtt-dub.py"
spec = importlib.util.spec_from_file_location("yt_vtt_dub", DUB)
dub = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dub)


def _write(tmp, lines):
    p = tmp / "turns.txt"
    p.write_text("\n".join(lines) + "\n")
    return p


def test_parse_txt_microturn_filter_and_merge(tmp_path):
    p = _write(tmp_path, [
        "0.0 5.0 SPEAKER_00",
        "5.2 9.0 SPEAKER_01",
        "9.1 9.3 SPEAKER_02",   # 0.2s micro-turn -> dropped
        "9.3 14.0 SPEAKER_00",
        "14.5 20.0 SPEAKER_02",
    ])
    turns, labels = dub.parse_diarize(p)
    assert labels == ["SPEAKER_00", "SPEAKER_01", "SPEAKER_02"]
    assert turns == [[0.0, 5.0, 0], [5.2, 9.0, 1],
                     [9.3, 14.0, 0], [14.5, 20.0, 2]]


def test_parse_rttm(tmp_path):
    p = _write(tmp_path, [
        "SPEAKER vid 1 0.000 5.000 <NA> <NA> A <NA> <NA>",
        "SPEAKER vid 1 5.200 3.800 <NA> <NA> B <NA> <NA>",
        "SPEAKER vid 1 9.300 4.700 <NA> <NA> A <NA> <NA>",
    ])
    turns, labels = dub.parse_diarize(p)
    assert labels == ["A", "B"]
    assert turns == [[0.0, 5.0, 0], [5.2, 9.0, 1], [9.3, 14.0, 0]]


def test_adjacent_same_speaker_merges_after_drop(tmp_path):
    p = _write(tmp_path, ["0 5 A", "5.1 5.2 B", "5.2 9 A"])
    turns, _ = dub.parse_diarize(p)
    assert turns == [[0.0, 9.0, 0]]


def test_min_turn_configurable(tmp_path):
    p = _write(tmp_path, ["0 0.5 A", "0.6 9 B"])
    turns, _ = dub.parse_diarize(p, min_turn=0.6)
    assert turns == [[0.6, 9.0, 1]]


def test_pitch_offset_families():
    sv = dub.speaker_voices(
        ["th-TH-NiwatNeural", "th-TH-PremwadeeNeural"], 5)
    assert sv == ["th-TH-NiwatNeural", "th-TH-PremwadeeNeural",
                  "th-TH-NiwatNeural@+8Hz", "th-TH-PremwadeeNeural@+8Hz",
                  "th-TH-NiwatNeural@-10Hz"]
    # explicit @pitch on the base spec is preserved for member 0
    sv = dub.speaker_voices(["th-TH-NiwatNeural@-4Hz"], 2)
    assert sv == ["th-TH-NiwatNeural@-4Hz", "th-TH-NiwatNeural@+8Hz"]


def test_anchor_speakers_extended_coverage():
    words = [[0.0, 0.4, "You're"], [0.4, 0.8, "a"], [0.8, 1.2, "fan"],
             [5.2, 5.6, "it's"], [5.6, 6.0, "my"], [6.0, 6.4, "song"]]
    turns = [[0.0, 5.0, 0], [5.0, 14.0, 1]]
    got = dub.anchor_speakers(
        {"Norton": "you're a fan", "Noel": "it's my song"}, words, turns)
    assert got[0][0] == "Norton" and got[1][0] == "Noel"
    # a phrase landing in inter-turn air claims the previous speaker's
    # extended range (matches voice_at semantics)
    got = dub.anchor_speakers({"X": "my song"}, words, turns)
    assert got[1][0] == "X"


def test_turns_to_cast_times_accepts_3_tuples():
    ct = dub.turns_to_cast_times([[0.0, 5.0, 0], [5.2, 9.0, 1]],
                                 ["V1", "V2"])
    assert ct == "V1:0.00-5.20;V2:5.20-9.00"
