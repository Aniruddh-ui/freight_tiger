"""Evaluation harness: is output/results.csv right, and can we trust it?

    python eval/evaluate.py [--results output/llm_groq/results.csv]   (run `python run.py` first)

Checks
  1. Labeled cases   - verdict and cited note for 12 hand/sample-labeled weeks.
  2. Recomputation   - every number recomputed from the raw CSV in plain Python
                       (no pandas, no shared code) and compared as text.
  3. Grounding audit - every justified row cites a note that applies to that
                       route, covers that week and says costs went up; no
                       other row has a note id.
  4. Sensitivity     - how many weeks get flagged under other thresholds, and
                       whether the labeled cases still pass.
"""
import csv
import json
import sys
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from cost_watch import config  # noqa: E402
from cost_watch.flagging import add_anomaly_flags  # noqa: E402
from cost_watch.load import load_shipments  # noqa: E402
from cost_watch.metrics import build_weekly_table  # noqa: E402
from cost_watch.notes import load_notes, overlaps_week  # noqa: E402

RESULTS = config.OUTPUT_DIR / "results.csv"
LABELS = ROOT / "eval" / "labels.csv"


def display_path(path: Path) -> str:
    """Project-relative path for the report, so it holds no machine-specific paths."""
    resolved = path.resolve()
    return str(resolved.relative_to(ROOT)) if resolved.is_relative_to(ROOT) else str(path)


def read_csv(path):
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def check_labels(results):
    by_key = {(r["route"], r["week_of"]): r for r in results}
    lines, passed = [], 0
    labels = read_csv(LABELS)
    for lab in labels:
        got = by_key[(lab["route"], lab["week_of"])]
        ok = got["flagged"] == lab["expected_flagged"] and got["matched_note_id"] == lab["expected_note_id"]
        passed += ok
        lines.append(f"| {'PASS' if ok else 'FAIL'} | {lab['route']} | {lab['week_of']} | "
                     f"{lab['expected_flagged']} {lab['expected_note_id']} | "
                     f"{got['flagged']} {got['matched_note_id']} | {lab['source']} |")
    return passed, len(labels), lines


def recompute_numbers():
    """Independent re-implementation of the brief's formulas with the stdlib only."""
    cost, tkm, rtype = defaultdict(float), defaultdict(float), {}
    for r in read_csv(config.SHIPMENTS_CSV):
        d = date.fromisoformat(r["shipment_date"])
        monday = d - timedelta(days=d.weekday())
        route = f"{r['origin']}-{r['destination']}"
        rtype[route] = r["route_type"]
        cost[(route, monday)] += float(r["freight_cost_inr"])
        tkm[(route, monday)] += float(r["quantity_tonnes"]) * float(r["distance_km"])
    cpk = {k: cost[k] / tkm[k] for k in cost}

    expected = {}
    for (route, week), value in cpk.items():
        prior = [cpk[(route, week - timedelta(weeks=i))] for i in range(1, 9)
                 if (route, week - timedelta(weeks=i)) in cpk]
        peers = [v for (r2, w2), v in cpk.items()
                 if w2 == week and r2 != route and rtype[r2] == rtype[route]]
        hist = f"{(value / (sum(prior) / len(prior)) - 1) * 100:+.1f}% vs this route's past average" \
            if prior else "n/a (no prior weeks)"
        peer = f"{(value / (sum(peers) / len(peers)) - 1) * 100:+.1f}% vs similar-length routes this week" \
            if peers else "n/a (no similar routes this week)"
        expected[(route, week.isoformat())] = (f"{value:.2f}", hist, peer)
    return expected


def check_numbers(results):
    expected = recompute_numbers()
    mismatches = [
        (r["route"], r["week_of"]) for r in results
        if expected.get((r["route"], r["week_of"])) !=
        (r["cost_per_tonne_km"], r["vs_own_history"], r["vs_similar_routes"])
    ]
    missing = len(expected) - len(results)
    return mismatches, missing, len(expected)


def check_grounding(results):
    notes = {n.note_id: n for n in load_notes(config.NOTES_CSV, config.NOTE_FACTS_JSON)}
    problems = []
    for r in results:
        nid, flagged = r["matched_note_id"], r["flagged"]
        if flagged != config.FLAG_JUSTIFIED:
            if nid:
                problems.append(f"{r['route']} {r['week_of']}: note id on a non-justified row")
            continue
        note = notes.get(nid)
        week = date.fromisoformat(r["week_of"])
        if note is None:
            problems.append(f"{r['route']} {r['week_of']}: cites unknown note {nid}")
        elif not (note.in_dataset and (note.all_routes or r["route"] in note.routes)):
            problems.append(f"{r['route']} {r['week_of']}: {nid} is for another route")
        elif not overlaps_week(note, week):
            problems.append(f"{r['route']} {r['week_of']}: {nid} does not cover this week")
        elif note.cost_effect != "increase":
            problems.append(f"{r['route']} {r['week_of']}: {nid} does not say costs rose")
        elif nid not in r["reason"]:
            problems.append(f"{r['route']} {r['week_of']}: reason does not name {nid}")
    justified = sum(r["flagged"] == config.FLAG_JUSTIFIED for r in results)
    return justified, problems


def sensitivity():
    weekly = build_weekly_table(load_shipments(config.SHIPMENTS_CSV))
    labeled_anomalies = {(lab["route"], lab["week_of"]) for lab in read_csv(LABELS)
                         if lab["expected_flagged"] != config.FLAG_NO}
    labeled_normal = {(lab["route"], lab["week_of"]) for lab in read_csv(LABELS)
                      if lab["expected_flagged"] == config.FLAG_NO}
    lines = []
    for own in (10, 15, 20):
        for peer in (15, 20, 25):
            flags = add_anomaly_flags(weekly, own, peer)
            hit = {(r.route, r.week_of.strftime("%Y-%m-%d")) for r in flags.itertuples() if r.is_anomaly}
            caught = len(labeled_anomalies & hit)
            false_alarms = len(labeled_normal & hit)
            chosen = " (chosen)" if (own, peer) == (config.OWN_HISTORY_THRESHOLD_PCT,
                                                    config.PEER_THRESHOLD_PCT) else ""
            lines.append(f"| {own}% | {peer}% | {len(hit)} | {caught}/{len(labeled_anomalies)} | "
                         f"{false_alarms}/{len(labeled_normal)} |{chosen}")
    return lines


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--results", type=Path, default=RESULTS)
    args = parser.parse_args()
    if not args.results.exists():
        sys.exit(f"{args.results} not found - run `python run.py` first")
    results = read_csv(args.results)
    report_path = args.results.parent / "eval_report.md"

    passed, total, label_lines = check_labels(results)
    mismatches, missing, n_expected = check_numbers(results)
    justified, problems = check_grounding(results)
    sens_lines = sensitivity()

    report = [
        "# Evaluation report", "", f"Results file: {display_path(args.results)}", "",
        f"## 1. Labeled cases: {passed}/{total} pass", "",
        "| result | route | week_of | expected | got | source |", "|---|---|---|---|---|---|",
        *label_lines, "",
        f"## 2. Independent recomputation: {n_expected - len(mismatches)}/{n_expected} rows match",
        "", f"Missing/extra rows: {missing}. Mismatches: {mismatches[:10] or 'none'}", "",
        f"## 3. Grounding audit: {justified} justified rows, {len(problems)} problems", "",
        *(f"- {p}" for p in problems), "",
        "## 4. Threshold sensitivity (anomalies flagged before note check)", "",
        "| own-history | peers | weeks flagged | labeled anomalies caught | labeled normals flagged |",
        "|---|---|---|---|---|", *sens_lines, "",
    ]
    report_path.write_text("\n".join(report))
    print("\n".join(report))

    ok = passed == total and not mismatches and missing == 0 and not problems
    print("OVERALL:", "PASS" if ok else "FAIL")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
