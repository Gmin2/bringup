"""Does the judge agree with the person?

The 102 hand ratings are the only ground truth in this project. A judge that
disagrees with them encodes someone else's taste, and training against it would
optimise for that instead. So the judge gets checked here before it is allowed
anywhere near a reward.

Agreement is measured only over pairs where the person picked a winner. A "both
good" or "both bad" rating is a statement about the pool, not a ranking, and
scoring the judge against it would muddle two different questions.

    python bench/judge_agreement.py --n 40
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from bringup.judge import VisionJudge
from bringup.providers import load_env
from bringup.render import RenderError, rasterize

ROOT = Path(__file__).resolve().parent.parent
PROMPTS = {p["id"]: p for p in json.loads((ROOT / "data/illus/prompts.json").read_text())}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default="2026-09-10")
    ap.add_argument("--n", type=int, default=40)
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--width", type=int, default=448)
    args = ap.parse_args()

    load_env()
    run_dir = ROOT / "runs" / args.run
    ratings = json.loads((run_dir / "ratings.json").read_text())

    decided = [r for r in ratings if r["winner"] in ("openai", "quiver", "qwen3-4b")]
    print(f"{len(ratings)} ratings, {len(decided)} with a named winner")
    todo = decided[: args.n]
    print(f"checking {len(todo)}\n")

    judge = VisionJudge()

    def one(r):
        p = PROMPTS[r["prompt_id"]]
        try:
            a = rasterize((run_dir / r["a"] / f"{r['prompt_id']}.svg").read_text(), width=args.width)
            b = rasterize((run_dir / r["b"] / f"{r['prompt_id']}.svg").read_text(), width=args.width)
        except (RenderError, FileNotFoundError) as e:
            return r, None, str(e)[:50]
        v = judge.compare(a, b, p["prompt"])
        return r, v, None

    rows = []
    with ThreadPoolExecutor(max_workers=args.jobs) as ex:
        for i, (r, v, err) in enumerate(ex.map(one, todo), 1):
            if err or v is None or v.error:
                print(f"  [{i:3}] {r['prompt_id']:14} skip: {err or v.error}")
                continue
            said = r["a"] if v.winner == "a" else r["b"] if v.winner == "b" else v.winner
            hit = said == r["winner"]
            rows.append({"prompt_id": r["prompt_id"], "family": r["family"],
                         "human": r["winner"], "judge": said, "agree": hit})
            print(f"  [{i:3}] {r['prompt_id']:14} human {r['winner']:9} judge {said:9} {'ok' if hit else 'MISS'}")

    if not rows:
        print("\nnothing scored")
        return 1

    agree = sum(r["agree"] for r in rows)
    biased = sum(1 for r in rows if r["judge"] == "biased")
    print(f"\nagreement {agree}/{len(rows)} = {100*agree/len(rows):.0f}%")
    print(f"position biased (answered the same side both ways): {biased}")

    print("\nby family")
    fams = sorted({r["family"] for r in rows})
    for f in fams:
        g = [r for r in rows if r["family"] == f]
        print(f"  {f:11} {sum(r['agree'] for r in g)}/{len(g)}")

    print("\nwhat the judge said when it disagreed")
    for k, v in Counter((r["human"], r["judge"]) for r in rows if not r["agree"]).most_common():
        print(f"  human said {k[0]:9} judge said {k[1]:9} x{v}")

    (run_dir / "judge_agreement.json").write_text(json.dumps(rows, indent=1))

    # a coin flip between two models is 50%. anything near that is not a judge.
    ok = agree / len(rows) >= 0.7
    print("\n" + ("judge tracks the human ratings, usable as a reward term"
                  if ok else "PROBLEM: judge does not track the ratings, do not use it as a reward"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
