"""Run the full analysis and write the output files.

    python run.py                 # deterministic, no LLM calls
    python run.py --llm groq      # reword explanations with open-weight gpt-oss-120b on Groq
    python run.py --llm claude    # same, with Claude

API keys are read from the environment or from a local .env file
(GROQ_API_KEY / ANTHROPIC_API_KEY).
"""
import argparse
import json
import os
from pathlib import Path

from cost_watch import config
from cost_watch.llm import GROQ_MODEL, REWRITERS, TokenLog
from cost_watch.output import check_columns_match_sample, write_results
from cost_watch.pipeline import analyse


def load_dotenv(path: Path) -> None:
    """Minimal .env reader: KEY=VALUE lines; real environment variables win."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip("'\""))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--llm", choices=["off", *REWRITERS], default="off")
    parser.add_argument("--out-dir", type=Path, default=config.OUTPUT_DIR)
    args = parser.parse_args()

    load_dotenv(config.ROOT / ".env")
    check_columns_match_sample(config.SAMPLE_OUTPUT_CSV)
    rewriter = REWRITERS[args.llm]() if args.llm != "off" else None

    results = analyse(rewriter=rewriter)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    write_results(results, args.out_dir / "results.csv")
    write_results(results[results["flagged"] != config.FLAG_NO], args.out_dir / "flagged_rows.csv")

    log = rewriter.log if rewriter else TokenLog(model="none (LLM off)")
    token_log = {"llm_mode": args.llm, "route_weeks": len(results), **log.to_dict()}
    if args.llm == "off":
        token_log["note"] = (
            "No LLM calls: verdicts, note matching and wording are deterministic. "
            f"With --llm groq, one {GROQ_MODEL} call is made per flagged or "
            "justified row to reword its reason."
        )
    (args.out_dir / "token_log.json").write_text(json.dumps(token_log, indent=2) + "\n")

    counts = results["flagged"].value_counts().to_dict()
    print(f"route-weeks: {len(results)}  verdicts: {counts}")
    print(f"llm: {json.dumps(log.to_dict())}")
    print(f"wrote {args.out_dir / 'results.csv'} and {args.out_dir / 'flagged_rows.csv'}")


if __name__ == "__main__":
    main()
