from datetime import date

import pandas as pd
import pytest

from cost_watch.config import NOTE_FACTS_JSON, NOTES_CSV
from cost_watch.explain import NO_NOTE_REASON, explain
from cost_watch.notes import load_notes, match_note, overlaps_week


@pytest.fixture(scope="module")
def notes():
    return {n.note_id: n for n in load_notes(NOTES_CSV, NOTE_FACTS_JSON)}


def flagged_row(route, week, vs_history=25.0, vs_peers=25.0):
    return {"route": route, "week_of": pd.Timestamp(week),
            "vs_history_pct": vs_history, "vs_peers_pct": vs_peers,
            "rise_vs_history": vs_history >= 15, "rise_vs_peers": vs_peers >= 20}


def test_every_note_with_no_cost_increase_is_marked_so(notes):
    # Cross-check the hand-written facts against tell-tale phrases in the raw text.
    no_effect_phrases = ["not significantly affected", "not part of this dataset",
                         "remained stable", "remained normal", "returned to normal",
                         "without a rate change", "improved road conditions"]
    for note in notes.values():
        if any(p in note.text for p in no_effect_phrases):
            assert note.cost_effect == "none", note.note_id


def test_only_n001_n002_n003_can_ever_justify(notes):
    assert {n.note_id for n in notes.values() if n.cost_effect == "increase"} == {"N001", "N002", "N003"}


@pytest.mark.parametrize("week, expected", [
    ("2025-02-17", False),  # week before flooding
    ("2025-02-24", True),
    ("2025-03-03", True),   # Mar 3-9 overlaps flooding until Mar 8
    ("2025-03-10", False),  # roads passable by Mar 9
])
def test_flood_window_boundaries(notes, week, expected):
    assert overlaps_week(notes["N001"], date.fromisoformat(week)) is expected


def test_festival_note_justifies_its_week_only(notes):
    nl = list(notes.values())
    assert match_note(flagged_row("Ahmedabad-Mumbai", "2025-01-20"), nl).note.note_id == "N002"
    assert match_note(flagged_row("Ahmedabad-Mumbai", "2025-01-27"), nl).note is None


def test_note_for_another_route_never_matches(notes):
    match = match_note(flagged_row("Mumbai-Pune", "2025-02-24"), list(notes.values()))
    assert match.note is None


def test_back_to_normal_note_is_rejected_with_its_reason(notes):
    match = match_note(flagged_row("Chennai-Bangalore", "2025-03-17"), list(notes.values()))
    assert match.note is None
    closest, why = match.rejected[0]
    assert closest.note_id == "N009"
    assert "does not describe a reason for a cost rise" in why


def test_unaffected_maintenance_note_does_not_justify(notes):
    match = match_note(flagged_row("Mumbai-Delhi", "2024-07-29"), list(notes.values()))
    assert match.note is None


def test_diesel_note_cannot_explain_a_gap_vs_peers(notes):
    row = flagged_row("Mumbai-Pune", "2025-05-05", vs_history=5.0, vs_peers=25.0)
    assert match_note(row, list(notes.values())).note is None


def test_diesel_note_cannot_explain_more_than_its_stated_size(notes):
    row = flagged_row("Delhi-Chennai", "2025-05-05", vs_history=18.0, vs_peers=0.0)
    assert match_note(row, list(notes.values())).note is None


def test_diesel_note_explains_a_rise_within_its_size(notes):
    # Only reachable with a lower threshold, but the rule itself must work.
    row = flagged_row("Delhi-Chennai", "2025-05-05", vs_history=6.0, vs_peers=0.0)
    row["rise_vs_history"] = True
    assert match_note(row, list(notes.values())).note.note_id == "N003"


def test_explain_outputs():
    assert explain(False, None)[0] == "No"
    flagged, note_id, reason = explain(True, None)
    assert (flagged, note_id, reason) == ("Yes", "", NO_NOTE_REASON)


def test_load_notes_rejects_made_up_evidence(tmp_path):
    import json
    facts = json.loads(NOTE_FACTS_JSON.read_text())
    facts["notes"][0]["evidence"].append("tolls doubled overnight")
    bad = tmp_path / "facts.json"
    bad.write_text(json.dumps(facts))
    with pytest.raises(ValueError, match="evidence quote not found"):
        load_notes(NOTES_CSV, bad)
