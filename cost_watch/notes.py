"""Find whether a context note genuinely explains a flagged cost rise.

A note justifies a flagged week only if ALL of these hold:
  1. it is about routes in this dataset,
  2. it applies to this route (by name, or "All Routes"),
  3. it says costs went UP (not "unaffected", "stable", "back to normal"),
  4. its date window overlaps the Monday-Sunday week,
  5. a nationwide note is not used to explain a gap vs similar routes
     (similar routes were hit by the same change),
  6. if the note states a size (e.g. "5-7%"), the rise vs history fits in it.
Each failed check produces a plain-English reason that we can show to a human.
"""
import json
from dataclasses import dataclass
from datetime import date, timedelta
from typing import List, Optional, Tuple

import pandas as pd

from .config import NEARBY_NOTE_DAYS


@dataclass(frozen=True)
class Note:
    note_id: str
    date: date
    applies_to: str
    text: str
    routes: Optional[Tuple[str, ...]]  # None means all routes
    in_dataset: bool
    window_start: date
    window_end: Optional[date]  # None means the change persists
    cost_effect: str  # "increase" or "none"
    max_effect_pct: Optional[float]
    summary: str
    what_it_says: str

    @property
    def all_routes(self) -> bool:
        return self.routes is None


@dataclass(frozen=True)
class NoteMatch:
    """Outcome of looking for a note for one flagged week."""
    note: Optional[Note]  # the note that justifies the rise, if any
    # Relevant notes that did NOT justify it, closest first, with the reason.
    rejected: Tuple[Tuple[Note, str], ...] = ()


def _to_date(value: Optional[str]) -> Optional[date]:
    return date.fromisoformat(value) if value else None


def load_notes(notes_csv, facts_json) -> List[Note]:
    """Join the raw notes with their structured facts and sanity-check them."""
    raw = pd.read_csv(notes_csv, dtype=str)
    with open(facts_json) as f:
        facts = {item["note_id"]: item for item in json.load(f)["notes"]}

    if set(raw["note_id"]) != set(facts):
        raise ValueError("note_facts.json does not cover exactly the notes in the CSV")

    notes = []
    for row in raw.itertuples(index=False):
        fact = facts[row.note_id]
        for quote in fact["evidence"]:
            if quote not in row.note:
                raise ValueError(f"{row.note_id}: evidence quote not found in note: {quote!r}")
        if fact["cost_effect"] not in ("increase", "none"):
            raise ValueError(f"{row.note_id}: unknown cost_effect {fact['cost_effect']!r}")
        routes = None if fact["routes"] == "ALL" else tuple(fact["routes"])
        notes.append(
            Note(
                note_id=row.note_id,
                date=date.fromisoformat(row.date),
                applies_to=row.applies_to,
                text=row.note,
                routes=routes,
                in_dataset=fact["in_dataset"],
                window_start=_to_date(fact["window_start"]),
                window_end=_to_date(fact["window_end"]),
                cost_effect=fact["cost_effect"],
                max_effect_pct=fact["max_effect_pct"],
                summary=fact["summary"],
                what_it_says=fact["what_it_says"],
            )
        )
    return sorted(notes, key=lambda n: (n.date, n.note_id))


def applies_to_route(note: Note, route: str) -> bool:
    return note.in_dataset and (note.all_routes or route in note.routes)


def overlaps_week(note: Note, week_of: date) -> bool:
    week_end = week_of + timedelta(days=6)
    starts_in_time = note.window_start <= week_end
    still_active = note.window_end is None or note.window_end >= week_of
    return starts_in_time and still_active


def days_from_week(note: Note, week_of: date) -> int:
    """Gap in days between the note's window and the week (0 if they overlap)."""
    if overlaps_week(note, week_of):
        return 0
    week_end = week_of + timedelta(days=6)
    if note.window_start > week_end:
        return (note.window_start - week_end).days
    return (week_of - note.window_end).days


def _window_text(note: Note) -> str:
    if note.window_end is None:
        return f"from {note.window_start.isoformat()} onwards"
    return f"{note.window_start.isoformat()} to {note.window_end.isoformat()}"


def support_failure(note: Note, route: str, week_of: date, row) -> Optional[str]:
    """Return None if the note supports this week's rise, else why it does not."""
    if not note.in_dataset:
        return "it concerns routes outside this dataset"
    if not applies_to_route(note, route):
        return f"it applies to {note.applies_to}, not {route}"
    if note.cost_effect != "increase":
        return "it does not describe a reason for a cost rise on this route"
    if not overlaps_week(note, week_of):
        return f"its window ({_window_text(note)}) does not include the week of {week_of.isoformat()}"
    if note.all_routes and row["rise_vs_peers"]:
        return ("a nationwide change raises similar routes too, so it cannot explain "
                f"this route being {row['vs_peers_pct']:+.1f}% above them")
    if note.max_effect_pct is not None and row["rise_vs_history"] \
            and row["vs_history_pct"] > note.max_effect_pct:
        return (f"it accounts for at most ~{note.max_effect_pct:g}%, but cost is "
                f"{row['vs_history_pct']:+.1f}% vs this route's past average")
    return None


def match_note(row, notes: List[Note]) -> NoteMatch:
    """Pick the note that justifies a flagged week, or the closest one that doesn't."""
    route = row["route"]
    week_of = row["week_of"].date() if hasattr(row["week_of"], "date") else row["week_of"]

    # Route-specific notes are more specific evidence than nationwide ones.
    def rank(note: Note):
        return (note.all_routes, days_from_week(note, week_of), note.note_id)

    supporting = [n for n in notes if support_failure(n, route, week_of, row) is None]
    if supporting:
        return NoteMatch(note=min(supporting, key=rank))

    # Nothing supports the rise. Collect the relevant notes we rejected so the
    # reason can say why: same route (or all routes), and either dated near the
    # week or with a window that covers it. Closest = nearest note date.
    nearby = [
        n for n in notes
        if applies_to_route(n, route)
        and (abs((n.date - week_of).days) <= NEARBY_NOTE_DAYS or overlaps_week(n, week_of))
    ]
    nearby.sort(key=lambda n: (abs((n.date - week_of).days), n.all_routes, n.note_id))
    rejected = tuple((n, support_failure(n, route, week_of, row)) for n in nearby)
    return NoteMatch(note=None, rejected=rejected)
