"""Wire the steps together: load -> weekly metrics -> flags -> notes -> output rows."""
import pandas as pd

from . import config
from .explain import explain
from .flagging import add_anomaly_flags
from .load import load_shipments
from .metrics import build_weekly_table
from .notes import load_notes, match_note
from .output import format_row


def analyse(
    shipments_csv=config.SHIPMENTS_CSV,
    notes_csv=config.NOTES_CSV,
    facts_json=config.NOTE_FACTS_JSON,
    rewriter=None,
) -> pd.DataFrame:
    """Return one output row per (route, week), already in the output schema."""
    weekly = add_anomaly_flags(build_weekly_table(load_shipments(shipments_csv)))
    notes = load_notes(notes_csv, facts_json)

    rows = []
    for row in weekly.to_dict("records"):
        match = match_note(row, notes) if row["is_anomaly"] else None
        flagged, note_id, reason = explain(row["is_anomaly"], match)
        if rewriter is not None and flagged != config.FLAG_NO:
            reason = rewriter.polish(reason)
        rows.append(format_row(row, flagged, note_id, reason))

    return pd.DataFrame(rows, columns=config.OUTPUT_COLUMNS)
