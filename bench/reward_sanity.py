"""Does the reward rank known-good plans above deliberately broken ones?

Everything after this depends on the answer, and it costs nothing to ask, so it
runs before any training does. Three things get checked:

  1. the 40 plans the frontier composer produced and the validator passed
     should score at or near the top
  2. every named degradation should score strictly lower than its clean parent
  3. more damage should score lower than less damage
"""

from __future__ import annotations

import json
import random
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from bench import degrade
from bringup.scorer import Scorer

VH = Path.home() / "coding/portfolio/ui/tools/svgs/vector-hardware"
PLANS = VH / "packages/web/public/dev/eval"
PROMPTS = VH / "packages/core/evals/prompts.json"

WEIGHTS = {"clean": 0.40, "structure": 0.10, "assembly": 0.10, "electrical": 0.10, "coverage": 0.30}


def load():
    expect = {p["id"]: p.get("expect", []) for p in json.load(open(PROMPTS))}
    out = []
    for f in sorted(PLANS.glob("*.json")):
        out.append((f.stem, json.load(open(f)), expect.get(f.stem, [])))
    return out


def main():
    cases = load()
    print(f"{len(cases)} plans from {PLANS}\n")
    rng = random.Random(0)

    with Scorer() as sc:
        clean = {}
        for name, plan, expect in cases:
            s = sc.score(plan, expect)
            clean[name] = s.total(WEIGHTS)
            if not s.ok or clean[name] < 0.999:
                print(f"  {name:22} {clean[name]:.3f}  {'; '.join(s.error_msgs())[:90]}")
        arr = np.array(list(clean.values()))
        print(f"clean plans: mean {arr.mean():.3f}  min {arr.min():.3f}  perfect {int((arr >= 0.999).sum())}/{len(arr)}\n")

        print("degradation                 n   mean    drop   worse than clean")
        rows = {}
        for kind, fn in degrade.ALL.items():
            deltas, totals = [], []
            for name, plan, expect in cases:
                bad = fn(plan, rng)
                if bad is None:
                    continue
                t = sc.score(bad, expect).total(WEIGHTS)
                totals.append(t)
                deltas.append(clean[name] - t)
            if not totals:
                continue
            rows[kind] = np.array(totals)
            worse = sum(d > 1e-9 for d in deltas)
            flag = "" if worse == len(deltas) else "   <-- NOT ALWAYS"
            print(f"{kind:24} {len(totals):4} {np.mean(totals):6.3f}  {np.mean(deltas):6.3f}   {worse}/{len(deltas)}{flag}")

        print("\nladder: k random degradations stacked")
        for k in range(0, 5):
            totals = []
            for name, plan, expect in cases:
                kinds = rng.sample(degrade.LADDER, k) if k else []
                bad, _ = degrade.stack(plan, kinds, seed=rng.randrange(10**6))
                totals.append(sc.score(bad, expect).total(WEIGHTS))
            print(f"  k={k}  mean {np.mean(totals):.3f}  min {np.min(totals):.3f}")

        print("\nterm correlation on the degraded pool (looking for redundancy)")
        names = ["clean", "structure", "assembly", "electrical", "coverage"]
        cols = {n: [] for n in names}
        for _ in range(6):
            for name, plan, expect in cases:
                kinds = rng.sample(degrade.LADDER, rng.randint(0, 3))
                bad, _ = degrade.stack(plan, kinds, seed=rng.randrange(10**6))
                s = sc.score(bad, expect)
                for n in names:
                    cols[n].append(s.terms.get(n) if s.terms.get(n) is not None else 1.0)
        m = np.array([cols[n] for n in names])
        print("            " + "".join(f"{n[:5]:>8}" for n in names))
        for i, n in enumerate(names):
            sd = m[i].std()
            line = "".join(
                f"{np.corrcoef(m[i], m[j])[0, 1]:8.2f}" if m[i].std() > 0 and m[j].std() > 0 else f"{'-':>8}"
                for j in range(len(names))
            )
            print(f"{n:>10}  {line}   std {sd:.3f}")


if __name__ == "__main__":
    main()
