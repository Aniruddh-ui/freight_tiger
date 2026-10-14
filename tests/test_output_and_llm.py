from types import SimpleNamespace

import pandas as pd

from cost_watch.config import OUTPUT_COLUMNS, SAMPLE_OUTPUT_CSV
from cost_watch.llm import ClaudeRewriter, GroqRewriter, is_safe_rewrite
from cost_watch.output import (check_columns_match_sample, format_pct,
                               read_sample_rows, write_results)
from cost_watch.pipeline import analyse

DRAFT = ("Matches note N002 dated 2025-01-20: a regional festival week drove a temporary "
         "surcharge on this corridor. The cost rise has a clear explanation.")


def test_output_columns_match_sample_exactly():
    check_columns_match_sample(SAMPLE_OUTPUT_CSV)


def test_format_pct():
    assert format_pct(35.52, "x", "n/a") == "+35.5% vs x"
    assert format_pct(-3.04, "x", "n/a") == "-3.0% vs x"
    assert format_pct(float("nan"), "x", "n/a") == "n/a"


def test_pipeline_reproduces_sample_rows():
    results = analyse()
    ours = results.set_index(["route", "week_of"])
    for s in read_sample_rows(SAMPLE_OUTPUT_CSV):
        row = ours.loc[(s["route"], s["week_of"])]
        for col in ["cost_per_tonne_km", "vs_own_history", "vs_similar_routes",
                    "flagged", "matched_note_id"]:
            assert row[col] == s[col], (s["route"], s["week_of"], col)
    assert list(results.columns) == OUTPUT_COLUMNS


def test_written_csv_round_trips(tmp_path):
    results = analyse()
    path = tmp_path / "results.csv"
    write_results(results, path)
    back = pd.read_csv(path, dtype=str, keep_default_na=False)
    assert back.equals(results)


def test_rewrite_validator_blocks_new_facts():
    ok = "Note N002 (2025-01-20) explains it: a festival-week surcharge hit this corridor."
    assert is_safe_rewrite(DRAFT, ok)
    assert not is_safe_rewrite(DRAFT, ok + " Diesel (N003) also rose.")       # new note id
    assert not is_safe_rewrite(DRAFT, ok.replace("2025-01-20", "2025-01-27"))  # new date
    assert not is_safe_rewrite(DRAFT, ok + " Costs rose 30%.")                # new number
    assert not is_safe_rewrite("Flagged for review.", "Costs look fine.")     # verdict lost
    assert not is_safe_rewrite(DRAFT, "Note N002 explains it: a festival surcharge.")  # date dropped


def test_rewrite_validator_blocks_meaning_drift():
    # Real gpt-oss rewrite seen in testing: a gap vs peers became a "rise".
    draft = ("The closest note (N003, 2025-05-05) describes a nationwide diesel price rise -- "
             "a nationwide change raises similar routes too, so it cannot explain this route "
             "being +20.6% above them. No genuine justification found; flagged for review.")
    drifted = ("The closest note (N003, 2025-05-05) reports a nationwide diesel increase, "
               "which cannot account for this route's 20.6% rise. Flagged for review.")
    kept = ("Note N003 (2025-05-05) describes a nationwide diesel price rise, but that lifts "
            "similar routes too, so it cannot explain this route being +20.6% above them; "
            "no genuine justification found, flagged for review.")
    assert not is_safe_rewrite(draft, drifted)
    assert is_safe_rewrite(draft, kept)


class FakeGroq:
    """Mimics groq.Groq().chat.completions.create."""

    def __init__(self, text, finish_reason="stop", fail=False):
        self.text, self.finish_reason, self.fail = text, finish_reason, fail
        self.chat = SimpleNamespace(completions=self)
        self.kwargs = None

    def create(self, **kwargs):
        self.kwargs = kwargs
        if self.fail:
            raise ConnectionError("rate limited")
        return SimpleNamespace(
            choices=[SimpleNamespace(finish_reason=self.finish_reason,
                                     message=SimpleNamespace(content=self.text))],
            usage=SimpleNamespace(prompt_tokens=120, completion_tokens=60),
        )


def test_groq_rewrite_is_accepted_and_typographic_hyphens_are_normalised():
    # gpt-oss really returned "2025‑01‑20" (non-breaking hyphens) in testing.
    client = FakeGroq("Note N002 (2025‑01‑20) explains it: a festival-week "
                      "surcharge hit this corridor.")
    rewriter = GroqRewriter(client=client)
    out = rewriter.polish(DRAFT)
    assert "2025-01-20" in out and "‑" not in out
    assert client.kwargs["temperature"] == 0 and client.kwargs["seed"] == 42
    log = rewriter.log.to_dict()
    assert (log["llm_calls"], log["input_tokens"], log["output_tokens"]) == (1, 120, 60)
    assert log["estimated_cost_usd"] == round((120 * 0.15 + 60 * 0.60) / 1e6, 6)


def test_groq_unfinished_answer_or_api_error_keeps_draft():
    assert GroqRewriter(client=FakeGroq("cut off", finish_reason="length")).polish(DRAFT) == DRAFT
    failing = GroqRewriter(client=FakeGroq("x", fail=True))
    assert failing.polish(DRAFT) == DRAFT
    assert failing.log.calls == 0 and failing.log.errors


class FakeClient:
    def __init__(self, text, stop_reason="end_turn"):
        self.text, self.stop_reason = text, stop_reason
        self.messages = self

    def create(self, **kwargs):
        return SimpleNamespace(
            stop_reason=self.stop_reason,
            content=[SimpleNamespace(type="text", text=self.text)],
            usage=SimpleNamespace(input_tokens=100, output_tokens=40),
        )


def test_rewriter_keeps_draft_when_rewrite_is_unsafe_and_logs_tokens():
    rewriter = ClaudeRewriter(client=FakeClient("Caused by N003 diesel."))
    assert rewriter.polish(DRAFT) == DRAFT
    assert rewriter.log.calls == 1 and rewriter.log.rejected_rewrites == 1
    assert rewriter.log.to_dict()["estimated_cost_usd"] == (100 * 4 + 40 * 20) / 1e6


def test_rewriter_falls_back_on_refusal():
    rewriter = ClaudeRewriter(client=FakeClient("anything", stop_reason="refusal"))
    assert rewriter.polish(DRAFT) == DRAFT
