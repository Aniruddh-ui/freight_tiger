"""Optional LLM step: reword an already-decided explanation, never decide it.

The verdict, matched note and numbers are fixed before the LLM sees anything.
The model only rewrites the wording, and `is_safe_rewrite` throws away any
rewrite that adds a note id, date or number that was not in the draft, or
drops one that was. If the API is unavailable or the answer is rejected we
keep the template text, so the output never depends on the LLM being right.

Backends:
  groq   - open-weight openai/gpt-oss-120b on Groq (default LLM; free tier)
  claude - claude-opus-5-5 via the Anthropic API
"""
import re
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

GROQ_MODEL = "openai/gpt-oss-120b"
CLAUDE_MODEL = "claude-opus-5-5"
# USD per 1M tokens (input, output), from each provider's published price list.
PRICES_PER_MTOK = {
    GROQ_MODEL: (0.15, 0.60),  # console.groq.com/docs/models
    CLAUDE_MODEL: (4.00, 20.00),
}
SEED = 42

SYSTEM_PROMPT = (
    "You rewrite short freight-cost audit explanations so they read naturally. "
    "Rules: keep the verdict exactly as stated; keep every note id, date and number "
    "exactly as written, using plain ASCII hyphens in dates; keep signed percentages "
    "(e.g. +20.6%) with their sign and keep what they are compared against (e.g. "
    "'similar routes', 'past average'); keep each note's stated reason for being "
    "rejected; do not add any fact, cause, number, date or note id that is not in "
    "the draft. "
    "Reply with the rewritten text only."
)

_NOTE_ID = re.compile(r"\bN\d{3}\b")
_DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
_NUMBER = re.compile(r"\d+(?:\.\d+)?")
_SIGNED_PCT = re.compile(r"[+-]\d+(?:\.\d+)?%")
_KEPT_PHRASES = ("similar routes", "past average", "nationwide", "does not include")
# Models sometimes emit typographic hyphens/dashes (e.g. U+2011 in "2025‑01‑20"),
# which would hide a date from the checks below.
_DASHES = str.maketrans({c: "-" for c in "‐‑‒–—−"})


def normalise(text: str) -> str:
    return text.translate(_DASHES).strip()


def is_safe_rewrite(draft: str, candidate: str) -> bool:
    """Accept a rewrite only if it keeps the draft's ids/dates and adds nothing."""
    if not candidate or len(candidate) > 2 * len(draft) + 100:
        return False
    if set(_NOTE_ID.findall(candidate)) != set(_NOTE_ID.findall(draft)):
        return False
    if set(_DATE.findall(candidate)) != set(_DATE.findall(draft)):
        return False
    if not set(_NUMBER.findall(candidate)) <= set(_NUMBER.findall(draft)):
        return False
    # Numbers must keep their meaning: "+20.6% above similar routes" must not
    # become "a 20.6% rise". Signed percentages and comparison phrases stay.
    if set(_SIGNED_PCT.findall(candidate)) != set(_SIGNED_PCT.findall(draft)):
        return False
    if any(p in draft.lower() and p not in candidate.lower() for p in _KEPT_PHRASES):
        return False
    # The verdict must survive: review-worthy stays review-worthy, justified stays justified.
    if ("review" in draft.lower()) != ("review" in candidate.lower()):
        return False
    return True


@dataclass
class TokenLog:
    model: str
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    rejected_rewrites: int = 0
    errors: List[str] = field(default_factory=list)

    def estimated_cost_usd(self) -> float:
        in_price, out_price = PRICES_PER_MTOK.get(self.model, (0.0, 0.0))
        return (self.input_tokens * in_price + self.output_tokens * out_price) / 1_000_000

    def to_dict(self) -> dict:
        return {
            "model": self.model,
            "llm_calls": self.calls,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "rejected_rewrites": self.rejected_rewrites,
            "estimated_cost_usd": round(self.estimated_cost_usd(), 6),
            "price_per_mtok_usd": PRICES_PER_MTOK.get(self.model),
            "errors": self.errors,
        }


class Rewriter:
    """Shared guardrails and token accounting; backends implement `_call`."""

    def __init__(self, model: str):
        self.model = model
        self.log = TokenLog(model=model)

    def _call(self, draft: str) -> Tuple[Optional[str], int, int]:
        """Return (text or None if the model did not finish, input_tokens, output_tokens)."""
        raise NotImplementedError

    def polish(self, draft: str) -> str:
        try:
            text, tokens_in, tokens_out = self._call(draft)
        except Exception as exc:  # network/auth/rate-limit problems must not break the run
            self.log.errors.append(f"{type(exc).__name__}: {exc}")
            return draft
        self.log.calls += 1
        self.log.input_tokens += tokens_in
        self.log.output_tokens += tokens_out
        candidate = normalise(text) if text else None
        if candidate and is_safe_rewrite(draft, candidate):
            return candidate
        self.log.rejected_rewrites += 1
        return draft


class GroqRewriter(Rewriter):
    """Open-weight model on Groq, at temperature 0 with a fixed seed."""

    def __init__(self, model: str = GROQ_MODEL, client=None):
        super().__init__(model)
        if client is None:
            from groq import Groq  # imported lazily so the default run needs no SDK

            client = Groq(max_retries=5)  # the free tier rate-limits; the SDK backs off
        self.client = client

    def _call(self, draft):
        response = self.client.chat.completions.create(
            model=self.model,
            temperature=0,
            seed=SEED,
            reasoning_effort="low",
            max_completion_tokens=1000,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f"Draft:\n{draft}"},
            ],
        )
        choice = response.choices[0]
        text = choice.message.content if choice.finish_reason == "stop" else None
        return text, response.usage.prompt_tokens, response.usage.completion_tokens


class ClaudeRewriter(Rewriter):
    """Claude via the Anthropic API (Opus 5.5 takes no temperature setting)."""

    def __init__(self, model: str = CLAUDE_MODEL, client=None):
        super().__init__(model)
        if client is None:
            import anthropic

            client = anthropic.Anthropic()
        self.client = client

    def _call(self, draft):
        response = self.client.messages.create(
            model=self.model,
            max_tokens=2000,
            output_config={"effort": "low"},
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": f"Draft:\n{draft}"}],
        )
        text = None
        if response.stop_reason == "end_turn":  # not refusal / max_tokens
            text = "".join(b.text for b in response.content if b.type == "text")
        return text, response.usage.input_tokens, response.usage.output_tokens


REWRITERS = {"groq": GroqRewriter, "claude": ClaudeRewriter}
