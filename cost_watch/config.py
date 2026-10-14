"""Paths and tunable settings in one place.

Anything marked DECISION is not specified by the case study brief; it is our
choice and is documented in the README.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
OUTPUT_DIR = ROOT / "output"

SHIPMENTS_CSV = DATA_DIR / "shipment_records.csv"
NOTES_CSV = DATA_DIR / "context_notes.csv"
SAMPLE_OUTPUT_CSV = DATA_DIR / "sample_output_format_v2.csv"
NOTE_FACTS_JSON = ROOT / "knowledge" / "note_facts.json"

# Specified by the brief: trailing 8-week window, strictly before the current week.
HISTORY_WINDOW_WEEKS = 8

# DECISION: the brief does not give an anomaly threshold. A week is flagged
# when cost is up by at least this much vs either baseline. Peer comparisons
# are noisier (different corridors, Short has only one peer), so the peer bar
# is higher. See eval/evaluate.py for the sensitivity table behind these.
OWN_HISTORY_THRESHOLD_PCT = 15.0
PEER_THRESHOLD_PCT = 20.0

# DECISION: how far from a week we look for a "closest note" to mention when
# no note justifies the rise. Only used for wording; never makes a row justified.
NEARBY_NOTE_DAYS = 28

# The output contract (column names and order), copied from the sample file.
OUTPUT_COLUMNS = [
    "route",
    "week_of",
    "cost_per_tonne_km",
    "vs_own_history",
    "vs_similar_routes",
    "flagged",
    "matched_note_id",
    "reason",
]

FLAG_YES = "Yes"
FLAG_JUSTIFIED = "No (justified)"
FLAG_NO = "No"
