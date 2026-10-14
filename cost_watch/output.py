"""Format result rows to match data/sample_output_format_v2.csv exactly."""
import csv
import math

import pandas as pd

from .config import OUTPUT_COLUMNS


def format_pct(value: float, label: str, missing: str) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return missing
    return f"{value:+.1f}% vs {label}"


def format_row(row: dict, flagged: str, note_id: str, reason: str) -> dict:
    return {
        "route": row["route"],
        "week_of": row["week_of"].strftime("%Y-%m-%d"),
        "cost_per_tonne_km": f"{row['cost_per_tonne_km']:.2f}",
        "vs_own_history": format_pct(
            row["vs_history_pct"], "this route's past average", "n/a (no prior weeks)"
        ),
        "vs_similar_routes": format_pct(
            row["vs_peers_pct"], "similar-length routes this week", "n/a (no similar routes this week)"
        ),
        "flagged": flagged,
        "matched_note_id": note_id,
        "reason": reason,
    }


def read_sample_rows(sample_csv) -> list:
    """Read the sample output tolerantly.

    The supplied sample has an unquoted comma inside one `reason` value, so a
    strict CSV parser sees 9 fields on that line. Everything after the 7th
    field is the reason, so we join it back together.
    """
    with open(sample_csv, newline="") as f:
        records = list(csv.reader(f))
    header, body = records[0], records[1:]
    n = len(header)
    return [dict(zip(header, r[: n - 1] + [",".join(r[n - 1:])])) for r in body]


def check_columns_match_sample(sample_csv) -> None:
    sample_columns = list(pd.read_csv(sample_csv, nrows=0).columns)
    if sample_columns != OUTPUT_COLUMNS:
        raise ValueError(f"output columns {OUTPUT_COLUMNS} != sample {sample_columns}")


def write_results(df: pd.DataFrame, path) -> None:
    df[OUTPUT_COLUMNS].to_csv(path, index=False)
