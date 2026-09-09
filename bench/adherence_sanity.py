"""Does CLIP actually tell our drawings apart?

A similarity score is worthless unless the right pairing beats the wrong one.
This scores every rendered output against every prompt and checks the diagonal
wins. If a model's drawing of a calendar does not score higher against the
calendar prompt than against the padlock prompt, the term carries no signal on
this kind of image and should not go in a reward.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from bringup.adherence import matrix, score_many
from bringup.render import rasterize

ROOT = Path(__file__).resolve().parent.parent
PROMPTS = ROOT / "data/illus/prompts.json"


def main() -> int:
    provider = sys.argv[1] if len(sys.argv) > 1 else "openai"
    run = sys.argv[2] if len(sys.argv) > 2 else "2026-09-10"
    d = ROOT / "runs" / run / provider

    prompts = json.loads(PROMPTS.read_text())
    have = [p for p in prompts if (d / f"{p['id']}.svg").exists()]
    if not have:
        print(f"no svgs in {d}")
        return 1
    print(f"{len(have)} outputs from {provider}\n")

    imgs = [rasterize((d / f"{p['id']}.svg").read_text(), width=336) for p in have]
    texts = [p["prompt"] for p in have]

    m = matrix(imgs, texts)
    diag = np.diag(m)
    off = m[~np.eye(len(have), dtype=bool)]

    rank = (m > diag[:, None]).sum(axis=1)  # how many wrong prompts beat the right one
    top1 = int((rank == 0).sum())

    print(f"matched   mean {diag.mean():.4f}  min {diag.min():.4f}  max {diag.max():.4f}")
    print(f"mismatched mean {off.mean():.4f}")
    print(f"separation {diag.mean() - off.mean():+.4f}")
    print(f"retrieval  {top1}/{len(have)} outputs score highest against their own prompt")
    print(f"median rank of the correct prompt: {int(np.median(rank)) + 1} of {len(have)}\n")

    worst = np.argsort(rank)[::-1][:6]
    print("worst matched (its own prompt beaten by this many others):")
    for i in worst:
        print(f"  {have[i]['id']:14} rank {rank[i] + 1:3}  sim {diag[i]:.3f}  "
              f"best match instead: {have[int(m[i].argmax())]['id']}")

    print("\nby family:")
    fams = sorted({p["family"] for p in have})
    for f in fams:
        idx = [i for i, p in enumerate(have) if p["family"] == f]
        print(f"  {f:11} n={len(idx):2}  matched {diag[idx].mean():.4f}  "
              f"top1 {int((rank[idx] == 0).sum())}/{len(idx)}")

    ok = top1 >= len(have) * 0.5 and diag.mean() - off.mean() > 0.02
    print("\n" + ("clip separates these drawings, the term carries signal"
                  if ok else "PROBLEM: clip cannot tell these apart, do not use it as a reward term"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
