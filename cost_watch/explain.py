"""Turn a flag decision and its note match into a verdict and a plain-English reason.

The reason is built only from the note facts and computed numbers, so every
statement in it can be traced back to the data.
"""
from typing import Optional, Tuple

from .config import FLAG_JUSTIFIED, FLAG_NO, FLAG_YES
from .notes import NoteMatch

NORMAL_REASON = (
    "Cost is within the normal range vs this route's history and similar routes; "
    "no review needed."
)
NO_NOTE_REASON = (
    "No matching note found for this route or date range. "
    "Cost rise looks unexplained and worth a human review."
)


def explain(is_anomaly: bool, match: Optional[NoteMatch]) -> Tuple[str, str, str]:
    """Return (flagged, matched_note_id, reason) for one route-week."""
    if not is_anomaly:
        return FLAG_NO, "", NORMAL_REASON

    if match is not None and match.note is not None:
        note = match.note
        reason = (
            f"Matches note {note.note_id} dated {note.date.isoformat()}: {note.summary}. "
            "The cost rise has a clear explanation."
        )
        return FLAG_JUSTIFIED, note.note_id, reason

    if match is not None and match.rejected:
        (closest, failure), others = match.rejected[0], match.rejected[1:]
        reason = (
            f"The closest note ({closest.note_id}, {closest.date.isoformat()}) "
            f"{closest.what_it_says} -- {failure}."
        )
        for note, why in others:
            reason += f" Also checked {note.note_id} ({note.date.isoformat()}): {why}."
        reason += " No genuine justification found; flagged for review."
        return FLAG_YES, "", reason

    return FLAG_YES, "", NO_NOTE_REASON
