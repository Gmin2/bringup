"""Which system prompt variant actually wins, judged head to head against base.

Gates and CLIP disagree about `detail` versus `craft`, and both are proxies.
The judge is the thing that was validated against real human ratings, so it is
what should settle it. Judges svgs already on disk rather than regenerating, so
this costs vision calls and nothing else.

    .venv/bin/python bench/pick_prompt.py craft detail
"""

from __future__ import annotations

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
EVOLVE = ROOT / "runs/evolve"


def png(variant: str, pid: str):
    f = EVOLVE / variant / f"{pid}.svg"
    if not f.exists():
        return None
    try:
        return rasterize(f.read_text(), width=512)
    except RenderError:
        return None


def main() -> int:
    load_env()
    variants = sys.argv[1:] or ["craft", "detail"]
    prompts = {p["id"]: p for p in json.loads((ROOT / "data/illus/prompts.json").read_text())}
    judge = VisionJudge()

    for v in variants:
        ids = sorted(f.stem for f in (EVOLVE / v).glob("*.svg") if f.stem in prompts)

        def one(pid):
            a, b = png("base", pid), png(v, pid)
            if a is None or b is None:
                return pid, "skipped"
            # a is base, b is the variant
            return pid, judge.compare(a, b, prompts[pid]["prompt"]).winner or "failed"

        with ThreadPoolExecutor(max_workers=3) as ex:
            rows = list(ex.map(one, ids))

        c = Counter(w for _, w in rows)
        wins, losses = c.get("b", 0), c.get("a", 0)
        print(f"{v:8} vs base   wins {wins}  losses {losses}  neither {c.get('neither',0)}  "
              f"biased {c.get('biased',0)}  skipped {c.get('skipped',0)}")
        for pid, w in rows:
            if w in ("b", "a"):
                print(f"    {pid:14} {'variant' if w == 'b' else 'base'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
