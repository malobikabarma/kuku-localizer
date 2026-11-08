"""Clicks through the app with a fake model. Run: API_BASE=mock pytest -q"""
import os
os.environ.setdefault("API_BASE", "mock")
from pathlib import Path

from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).resolve().parents[1] / "app.py")


def _click(at, label):
    next(b for b in at.button if b.label.startswith(label)).click().run()
    assert not at.exception, at.exception


def test_demo_and_studio_actions():
    at = AppTest.from_file(APP, default_timeout=120).run()
    assert not at.exception
    next(b for b in at.sidebar.button if b.label == "Load demo").click().run()
    assert not at.exception, at.exception
    res = next(iter(at.session_state["results"].values()))
    kinds = {f["type"] for f in res["qa"]["flags"]}
    assert {"variant", "timing"} <= kinds          # the two planted mistakes are caught
    for label in ["Accept all unflagged", "Save edits and re-check", "Apply AI judge suggestions",
                  "Plant mistakes and run QA", "Resolve labels"]:
        _click(at, label)
