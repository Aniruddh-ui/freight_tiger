# Freight cost watcher (FreightTiger intern case study)

This tool tracks weekly cost per tonne-km for each route. It flags weeks where the cost rises unusually, then checks the context notes for a real reason. It only marks a rise as justified when a note genuinely supports it.

## Brief checklist

| The brief asks for | Where |
|---|---|
| Group by route and the given `route_type`; weekly (Mon–Sun) cost per tonne-km | `cost_watch/metrics.py` |
| vs own history: trailing 8-week average, strictly prior weeks; fewer than 8 explained | `metrics.add_history_baseline`, Decisions table below |
| vs similar routes: same week, same `route_type`, route itself excluded | `metrics.add_peer_baseline` |
| Flag unusual rises | `cost_watch/flagging.py`, threshold in Decisions table |
| Check notes; justified only with the exact note for that route and time | `cost_watch/notes.py`, `knowledge/note_facts.json` |
| Plain-English reason backed by the notes, not made up | `cost_watch/explain.py`, optional LLM wording with guardrails in `cost_watch/llm.py` |
| Stretch: ask questions in plain English | `ask.py` |
| Output CSV in the exact sample format, incl. `matched_note_id` | `output/results.csv` |
| Eval harness / labeled set | `eval/`, `output/eval_report.md` |
| 3-run reproducibility check | `output/repro_off/`, `output/repro_groq/` |
| Token/cost log for one full run | `output/token_log.json`, `output/llm_groq/token_log.json` |

## Run it

Requires Python 3.11+ (tested on 3.12).

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python run.py                  # writes output/results.csv, flagged_rows.csv, token_log.json
.venv/bin/python -m pytest -q            # 33 unit tests
.venv/bin/python eval/evaluate.py        # eval harness -> output/eval_report.md
.venv/bin/python scripts/repro_check.py  # 3 fresh runs -> output/repro_off/repro_report.md
.venv/bin/python ask.py "why did Chennai-Bangalore get pricier in March?"

# Optional LLM wording (open-weight gpt-oss-120b on Groq's free tier):
cp .env.example .env    # then put your key after GROQ_API_KEY=
.venv/bin/python run.py --llm groq --out-dir output/llm_groq
.venv/bin/python eval/evaluate.py --results output/llm_groq/results.csv
.venv/bin/python scripts/repro_check.py --llm groq   # -> output/repro_groq/repro_report.md
```

## Outputs

| file | what |
|---|---|
| `output/results.csv` | **Main deliverable.** One row for every route-week (7 routes × 104 weeks = 728), with exactly the columns of `sample_output_format_v2.csv` |
| `output/flagged_rows.csv` | Same schema, only the `Yes` and `No (justified)` rows (20) |
| `output/token_log.json` | LLM calls, tokens and cost for the run |
| `output/eval_report.md` | Eval harness results |
| `output/repro_off/repro_report.md` | 3-run reproducibility check (no LLM) |
| `output/llm_groq/` | Same outputs with reasons reworded by gpt-oss-120b, plus its eval report and real token log |
| `output/repro_groq/repro_report.md` | 3-run reproducibility check with the LLM on |

`flagged` takes three values: `Yes` (unusual and unexplained), `No (justified)` (unusual but explained by a note, with the note in `matched_note_id`), and `No` (normal week).

## How it works

```
shipment_records.csv ─► load.py ─► metrics.py ─► flagging.py ─► notes.py ─► explain.py ─► output.py
                       validate    weekly cost    threshold      does a note   verdict +     exact
                                   + baselines    rule           justify it?   reason        schema
```

1. **load.py** validates the data: columns, blanks, duplicate IDs, positive quantities and distances, and one `route_type` per route. It fails loudly rather than dropping rows. Route = `origin-destination`.
2. **metrics.py** does the weekly maths:
   * `week_of` = Monday of the Monday–Sunday week.
   * Weekly cost per tonne-km = Σ freight cost / Σ (tonnes × km) for that route and week. The alternative, a mean of per-shipment ratios, gives 4.16 instead of the sample's 4.17. Only the totals version reproduces all three sample rows exactly.
   * **vs own history**: the average weekly cost over the 8 calendar weeks strictly before this week. The current week is never included.
   * **vs similar routes**: the plain average of the *other* routes with the same `route_type` in the same week. The route itself is excluded.
3. **flagging.py** applies the threshold rule (see Decisions).
4. **notes.py** checks a flagged week against the notes. A note justifies the week only if **all** of these hold:
   1. it is about routes in this dataset (N004 is not);
   2. it applies to this route, by name or "All Routes";
   3. it says costs went **up**. "Not significantly affected", "stable", "returned to normal" and "absorbed without a rate change" do not count;
   4. its date window overlaps the week;
   5. a nationwide note (diesel, N003) is never used to explain a gap vs similar routes, because those routes had the same rise;
   6. if the note gives a size (N003: "roughly 5-7%"), the rise vs history must fit inside it.
5. **explain.py** writes the reason from templates filled with the note's facts and the computed numbers. When nothing justifies a week, it names the closest relevant note(s) and gives the specific check each one failed.

### The knowledge base: `knowledge/note_facts.json`

There are only 10 notes. I read each one into structured fields: routes, date window, whether it says costs rose, and a stated size. Every field is backed by **verbatim evidence quotes**, and `load_notes` refuses to run if any quote does not appear in the note text. A test also cross-checks that every note containing a "no effect" phrase is marked `cost_effect: none`.

Why not a vector database? With 10 short notes, embedding similarity would add a non-deterministic step and new ways to fail. For example, "flood" ≈ "flood-related repairs" would wrongly surface N009 as support. The hard part is not finding notes but deciding whether a note *applies*: right route, right dates, and a real cost increase. Explicit checks do that reliably and can say why a note was rejected. With hundreds of notes, I would add an embedding or BM25 step to shortlist candidates *before* these same checks.

### Where the LLM fits (optional, `--llm groq`)

The LLM never decides anything. Verdicts, note IDs and numbers are fixed first. With `--llm groq`, the open-weight **`openai/gpt-oss-120b`** (Apache-2.0) on Groq's free tier rewords the reason for each flagged or justified row: 20 calls per full run, `temperature=0`, `seed=42`, `reasoning_effort="low"`. `--llm claude` uses the same interface with `claude-opus-5-5`.

`is_safe_rewrite` then checks every rewrite against its draft. It must keep exactly the same note IDs and dates, keep every signed percentage (e.g. `+20.6%`) and comparison phrase ("similar routes", "past average", "nationwide", "does not include"), add no new numbers, and keep the "review" verdict. A rejected rewrite, an unfinished answer or an API error all fall back to the template text.

The checks were tightened after testing on the real model, which showed two failure modes:
* gpt-oss wrote dates with Unicode non-breaking hyphens (`2025‑01‑20`), which hid them from the date check. Text is now normalised before checking.
* Some rewrites turned "+20.6% above similar routes" into "a 20.6% rise". All the numbers came from the draft, but the meaning was wrong. Signed percentages and comparison phrases must now be preserved.

With the tighter checks, **4–5 of 20 rewrites per run are rejected** (5 in each of the runs committed here) and keep the template wording. The deterministic `output/results.csv` is the primary deliverable, and `output/llm_groq/` has the same verdicts with LLM wording.

## Decisions the brief leaves open

| topic | decision | why |
|---|---|---|
| **Anomaly threshold** | Flag if cost is **≥ +15% vs own history OR ≥ +20% vs similar routes** (`config.py`) | Not specified in the brief. Across all 728 weeks, vs-history changes have a std of ~4.2% (99th pct 11%). Vs-peer changes are noisier: std ~9%, 95th pct 13%, and Short routes have only one peer. So the peer bar is higher. These thresholds catch all three sample rows. The sensitivity table in `eval_report.md` shows 13–28 flagged weeks over the 10–20% / 15–25% grid. |
| "Rising" | A positive change past the threshold on *either* baseline | Mumbai-Pune creeps up slowly. Its own 8-week average creeps up with it, so only the peer comparison catches it. This is the case in the sample's 2025-09-15 row (+9.2% / +23.6%). |
| Fewer than 8 prior weeks | Average whatever prior weeks exist. The first week of each route shows `n/a (no prior weeks)` and can only be flagged on peers | As the brief asks: no padding. This affects weeks 2024-01-01 to 2024-02-19, which use 0–7 prior weeks. |
| 8-week window | Calendar-based (`[week−8w, week)`), not "last 8 rows" | If a route ever skips a week, row-based windows would silently reach further back. The data has no gaps today (all 7 routes have all 104 weeks), so both give the same numbers. A test covers the gap case. |
| Note windows without an end date | N002 "festival week" = that one week. N005 "about a week" = that week. N003 diesel = open-ended. Other notes use their own week | Taken from the note wording. Only N001, N002 and N003 claim a cost increase, so the windows of the other notes never change a verdict. |
| Output rows | Every route-week in `results.csv`, plus a flagged-only file | The sample only shows unusual rows, but including every week lets the weekly numbers be checked. |
| Rounding | Computed at full precision, formatted at the end: cost to 2 dp, % to 1 dp with a sign | Matches the sample. |

## How I convinced myself it is right

* **The sample rows reproduce exactly**: cost, both % strings, `flagged` and `matched_note_id` for all 3 sample rows (`tests/test_output_and_llm.py`).
* **Independent recomputation** (`eval/evaluate.py`): every number is recomputed from the raw CSV in plain Python, with no pandas and no shared code, and compared as text. **728/728 match.**
* **Labeled set**: 12 weeks (3 from the sample, 9 labeled by hand with a reason each in `eval/labels.csv`), including the traps. **12/12 pass.**
  * Chennai-Bangalore 2025-02-24 and 2025-03-03 → justified by N001. The week Mar 3–9 overlaps flooding that lasted until Mar 8.
  * Chennai-Bangalore 2025-03-10 → **flagged**. The roads were passable again by Mar 9, yet cost is still +22%.
  * Chennai-Bangalore 2025-03-17 → **flagged**. N009 says "returned to normal", which is not a reason for a rise.
  * Mumbai-Pune creep (+20–39% vs Delhi-Jaipur in H2 2025) → **flagged**. The diesel note hits both routes, so it cannot explain the gap.
  * Mumbai-Delhi 2024-07-29 (N005, "costs not significantly affected") → not flagged, and N005 can never justify a week.
* **Grounding audit**: every justified row cites a note that applies to that route, covers that week and says costs rose, and the reason names the note. **0 problems.** No non-justified row carries a note ID.
* **Unit tests (33)**: week boundaries (a Sunday belongs to the previous Monday's week), totals-vs-mean aggregation, no look-ahead, partial history, calendar window with a missing week, peer exclusion, threshold edges, flood-window boundaries, each type of note rejection, fabricated evidence quotes rejected, the LLM rewrite guard (including the two real gpt-oss failures above), API-error fallback, and token accounting with fake clients.
* **The LLM output gets the same eval**: `output/llm_groq/eval_report.md` also passes (12/12 labels, 728/728 numbers, 0 grounding problems).

Caveat: I wrote 9 of the 12 labels myself after reading the data and the notes, so they test the rules against my reading rather than against an outside ground truth.

## Reproducibility

`scripts/repro_check.py` runs `run.py` three times in fresh processes and compares the results.

| mode | flags, note IDs, numbers | whole file |
|---|---|---|
| LLM off (`output/repro_off/`) | identical | **byte-identical** (same sha256) |
| `--llm groq` (`output/repro_groq/`) | identical, and identical to the LLM-off run | wording differs (5 of 20 reasons differ between runs 1 and 2, 7 between runs 1 and 3) |

Groq's `temperature=0` + `seed=42` makes wording close but not guaranteed identical. Verdicts and numbers are computed before the LLM runs and the LLM cannot change them, so the variation is limited to wording, as the brief allows.

## Token / cost log

| run | LLM calls | input tokens | output tokens | cost |
|---|---|---|---|---|
| Default (LLM off), `output/token_log.json` | 0 | 0 | 0 | $0.00 |
| `--llm groq`, gpt-oss-120b, `output/llm_groq/` | 20 | 5,527 | 2,417 | $0.0023 |
| `--llm groq`, repro run 1 | 20 | 5,783 | 2,410 | $0.0023 |
| `--llm groq`, repro run 2 | 20 | 5,783 | 2,388 | $0.0023 |
| `--llm groq`, repro run 3 | 20 | 6,039 | 2,372 | $0.0023 |

Input tokens vary slightly between runs even though the prompts are the same; these are Groq's own reported counts. These are the exact `usage` totals returned by the API (`token_log.json` in each run folder). Cost is at Groq's published rate of $0.15 / $0.60 per million input/output tokens. Output includes gpt-oss's reasoning tokens. On Groq's free tier the actual charge is $0. That is one call per flagged or justified row, never per shipment, so cost grows with the number of anomalies, not the size of the file.

## Known limitations

* The note facts are hand-curated. That works for 10 notes; for many notes, an LLM extraction step would fill the same JSON and the evidence-quote check would stay in place as a guard.
* Thresholds are global. Per-route thresholds based on each route's own variability would be the next improvement.
* `data/sample_output_format_v2.csv` has an unquoted comma inside one `reason` value, `(N006, 2025-09-22)`, so strict CSV parsers read 9 fields on that line. Our writer quotes properly, and the tests read the sample tolerantly.

## Layout

```
cost_watch/   config, load, metrics, flagging, notes, explain, llm, output, pipeline
knowledge/    note_facts.json (structured notes + evidence quotes)
data/         the supplied CSVs (unchanged; the brief PDF is kept out of git)
eval/         labels.csv, evaluate.py
scripts/      repro_check.py
tests/        unit tests
output/       generated deliverables (committed so they can be reviewed without running)
run.py, ask.py, requirements.txt, .env.example
```
