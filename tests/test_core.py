"""Run with:  API_BASE=mock pytest -q"""
import os
os.environ.setdefault("API_BASE", "mock")
from pathlib import Path

import evaluation as ev
import glossary as gl
import pipeline
import qa
import screenplay as sp
import timing

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = (ROOT / "sample" / "sample_episode.txt").read_text(encoding="utf-8")


def test_parser_reads_sample():
    ep = sp.parse(SAMPLE, "sample")
    assert len(ep.dialogue) == 17 and len(ep.scenes) == 2 and not ep.warnings
    first = ep.dialogue[0]
    assert first.speaker == "MEERA" and first.emotion == "Shocked, Whispering" and first.start == 1.2


def test_label_parsing():
    assert sp.split_label("JULIANA (V.O.) (Reflective, Vulnerable)") == ("JULIANA", "V.O.", "Reflective, Vulnerable")
    assert sp.split_label("LORD ASHCROFT (O.S. / Continues)") == ("LORD ASHCROFT", "O.S.", "")


def test_syllables():
    assert timing.count_syllables("राम") == 1
    assert timing.count_syllables("रोहन") == 2
    assert timing.count_words("मैं अब उसकी पत्नी हूँ।") == 5


def test_variant_detection():
    assert qa._is_variant("मिरा", "मीरा")
    assert qa._is_variant("जुलियाना", "जूलियाना")
    assert not qa._is_variant("मेरा", "मीरा")
    assert not qa._is_variant("पिता", "पिताजी")


def test_seeded_errors_are_caught():
    ep = sp.parse(SAMPLE, "sample")
    entries = [gl.Entry("character", "Meera", "मीरा"), gl.Entry("character", "Rohan", "रोहन")]
    res = pipeline.run_episode(ep, "Hindi", entries)
    mutated, truth = ev.seed(ep, res["targets"], entries, "Hindi", n_names=0, n_timing=3, flatten_cliffhanger=False)
    out = ev.evaluate(ep, res["targets"], mutated, truth, entries, "Hindi")
    assert out["recall"] == 1.0
