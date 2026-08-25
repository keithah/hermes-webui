"""Regression checks for Hindsight state across profile switches."""
from pathlib import Path


PANELS = (Path(__file__).resolve().parents[1] / "static" / "panels.js").read_text(encoding="utf-8")


def test_profile_switch_invalidates_hindsight_state_and_late_requests():
    assert "function _resetHindsightState()" in PANELS
    reset_start = PANELS.index("function _resetHindsightState()")
    reset_body = PANELS[reset_start:PANELS.index("\n}\n", reset_start) + 2]
    for state in ("_hindsightResults = []", "_hindsightReflectText = ''", "_hindsightLastQuery = ''", "_hindsightReflectQuery = ''", "++_hindsightRecallSeq", "++_hindsightReflectSeq"):
        assert state in reset_body
    switch_start = PANELS.index("async function _profileSwitchPanelLoad()")
    switch_body = PANELS[switch_start:PANELS.index("\n}\n", switch_start) + 2]
    assert "_resetHindsightState();" in switch_body


def test_all_hindsight_fetches_drop_late_cross_profile_responses():
    for function_name in ("loadHindsightStatus", "loadHindsightMemories"):
        start = PANELS.index(f"async function {function_name}")
        body = PANELS[start:PANELS.index("\n}\n", start) + 2]
        assert "_hindsightProfileName()" in body
        assert "profile !== _hindsightProfileName()" in body
