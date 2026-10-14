"""Run the pipeline three times from scratch and confirm the outputs are identical.

    python scripts/repro_check.py [--llm groq]

Each run is a separate process writing to output/repro_<llm>/run_N/. With the LLM
on, only the reason wording may differ; flags, note ids and numbers must not.
"""
import argparse
import csv
import hashlib
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = ROOT / "output"
FIXED_COLUMNS = ["route", "week_of", "cost_per_tonne_km", "vs_own_history",
                 "vs_similar_routes", "flagged", "matched_note_id"]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fixed_part(path: Path) -> list:
    with open(path, newline="") as f:
        return [tuple(r[c] for c in FIXED_COLUMNS) for r in csv.DictReader(f)]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--llm", choices=["off", "groq", "claude"], default="off")
    args = parser.parse_args()
    repro_dir = OUTPUT_DIR / f"repro_{args.llm}"

    runs = []
    for i in (1, 2, 3):
        out_dir = repro_dir / f"run_{i}"
        subprocess.run([sys.executable, str(ROOT / "run.py"), "--llm", args.llm,
                        "--out-dir", str(out_dir)], check=True, cwd=ROOT,
                       stdout=subprocess.DEVNULL)
        runs.append(out_dir / "results.csv")

    hashes = [sha256(p) for p in runs]
    fixed_same = fixed_part(runs[0]) == fixed_part(runs[1]) == fixed_part(runs[2])
    files_same = len(set(hashes)) == 1

    lines = ["# Reproducibility check (3 runs)", "", f"LLM mode: {args.llm}", ""]
    lines += [f"- run_{i}: sha256 {h}" for i, h in enumerate(hashes, 1)]
    lines += ["",
              f"Flags, note ids and numbers identical across runs: {'YES' if fixed_same else 'NO'}",
              f"Whole files byte-identical: {'YES' if files_same else 'NO'}"]
    report = "\n".join(lines) + "\n"
    (repro_dir / "repro_report.md").write_text(report)
    print(report)
    sys.exit(0 if fixed_same else 1)


if __name__ == "__main__":
    main()
