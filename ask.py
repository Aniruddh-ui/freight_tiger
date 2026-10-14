"""Ask a plain-English question about the findings (stretch goal).

    python ask.py "why did Chennai-Bangalore get pricier in March?"
    python ask.py "anything unusual on Mumbai-Pune in 2025?"

Answers come only from output/results.csv: we find the route and month/year
named in the question and quote the matching rows. No LLM, so it cannot
invent an answer; if nothing matches it says so.
"""
import calendar
import re
import sys

import pandas as pd

from cost_watch import config

MONTHS = {name.lower(): i for i, name in enumerate(calendar.month_name) if name}
MONTHS.update({name.lower(): i for i, name in enumerate(calendar.month_abbr) if name})


def parse_question(question: str, routes):
    q = question.lower()
    route = next((r for r in routes if r.lower() in q), None)
    if route is None:  # allow a single city name, e.g. "Pune"
        hits = [r for r in routes if any(city.lower() in q for city in r.split("-"))]
        route = hits[0] if len(hits) == 1 else None
    month = next((m for name, m in MONTHS.items() if re.search(rf"\b{name}\b", q)), None)
    year_match = re.search(r"\b(2024|2025)\b", q)
    return route, month, int(year_match.group()) if year_match else None


def answer(question: str, results: pd.DataFrame) -> str:
    route, month, year = parse_question(question, sorted(results["route"].unique()))
    rows = results[results["flagged"] != config.FLAG_NO]
    if route:
        rows = rows[rows["route"] == route]
    weeks = pd.to_datetime(rows["week_of"])
    if month:
        rows = rows[weeks.dt.month == month]
    if year:
        rows = rows[pd.to_datetime(rows["week_of"]).dt.year == year]

    scope = " ".join(str(x) for x in [route or "all routes", calendar.month_name[month] if month else "",
                                      year or ""] if x)
    if rows.empty:
        return f"No unusual cost rises were found for {scope}."
    lines = [f"Unusual cost weeks for {scope}:"]
    for r in rows.itertuples(index=False):
        lines.append(f"- {r.route}, week of {r.week_of}: {r.cost_per_tonne_km}/tonne-km, "
                     f"{r.vs_own_history}, {r.vs_similar_routes}. Verdict: {r.flagged}. {r.reason}")
    return "\n".join(lines)


def main() -> None:
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    path = config.OUTPUT_DIR / "results.csv"
    if not path.exists():
        sys.exit("output/results.csv not found - run `python run.py` first")
    results = pd.read_csv(path, dtype=str, keep_default_na=False)
    print(answer(" ".join(sys.argv[1:]), results))


if __name__ == "__main__":
    main()
