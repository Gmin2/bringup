"""How well does a model draw the narrowed brief: isometric product illustration.

The system prompt here is the narrowed scope, derived from the pixel-perfect
assets and the two Illustrator tutorials: true 30 degree projection, uniform
outline with thinner interior detail, flat fills in one hue at three values
keyed to face orientation.

    python -m bringup.iso_probe --provider openai --run iso-probe
"""

from __future__ import annotations

import argparse
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import bringup.providers as P
from bringup.gates import check
from bringup.providers import OpenAIProvider, load_env
from bringup.render import RenderError, rasterize, save_png

ROOT = Path(__file__).resolve().parent.parent

SYSTEM = """You draw isometric product illustrations as SVG. Reply with one complete SVG document and nothing else: no prose, no markdown fence, no explanation.

Projection: true 30 degree isometric. The two horizontal axes run along (0.866, 0.5) and (-0.866, 0.5); vertical edges stay vertical on screen. Every face lies on one of those three planes. Squares in 3D must come out as rhombi, never as rectangles.

Line: outline every solid with a uniform heavier stroke. Interior detail lines are noticeably thinner. Rounded caps and joins.

Fill: flat only, one hue at three values keyed to face orientation. Top faces lightest, one side mid, the other side darkest. The outline is a saturated version of the same hue.

Never use: gradients, <image>, <foreignObject>, scripts, animation, external references.

Draw a real object with recognisable parts. Between 30 and 120 elements."""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--provider", default="openai")
    ap.add_argument("--run", default="iso-probe")
    ap.add_argument("--jobs", type=int, default=3)
    args = ap.parse_args()

    load_env()
    P.SYSTEM = SYSTEM          # the providers read this at call time
    prov = OpenAIProvider()
    prompts = json.loads((ROOT / "data/illus/iso_prompts.json").read_text())
    out = ROOT / "runs" / args.run / args.provider
    out.mkdir(parents=True, exist_ok=True)

    def one(p):
        g = prov.generate(p["prompt"], p["id"], timeout=300)
        if not g.ok:
            return f"{p['id']:14} FAILED {g.error}"
        (out / f"{p['id']}.svg").write_text(g.svg)
        r = check(g.svg)
        try:
            save_png(rasterize(g.svg, width=460), out / f"{p['id']}.png")
        except RenderError as e:
            return f"{p['id']:14} render failed: {e}"
        return (f"{p['id']:14} {g.ms//1000:3}s  {r.info.get('bytes'):6}b  "
                f"{r.info.get('shapes'):3} shapes  gates={r.passed} {r.reasons or ''}")

    with ThreadPoolExecutor(max_workers=args.jobs) as ex:
        for line in ex.map(one, prompts):
            print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
