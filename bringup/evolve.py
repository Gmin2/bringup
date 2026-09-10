"""Search for a better system prompt.

Surya went straight from a base model to GRPO without any supervised stage. What
made that work was evolving the system prompt first, and his finding was
specific: a strict allowlist of eight brush methods with no api reference beat a
400-line reference, because the long docs made the model hallucinate methods
that did not exist.

Our failure is a different one. Qwen3-4B emits valid svg on 34 of 34 and passes
gates on 31, so it is not hallucinating elements. It draws thin: 2.7KB against
gpt's 13.5KB on the same brief, and it wins 5.5% of hand-rated comparisons. So
the variants here push on structure and detail rather than on constraint.

Scored by the judge, because gates and clip both said qwen was competitive and
the hand ratings said 5.5%. Optimising against a metric the ratings already
contradicted would just find the prompt that games it.

    python -m bringup.evolve --n 6 --jobs 3
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from bringup.gates import check
from bringup.judge import VisionJudge
from bringup.providers import OpenAIProvider, load_env
from bringup.render import RenderError, rasterize

ROOT = Path(__file__).resolve().parent.parent
PROMPTS = ROOT / "data/illus/prompts.json"

BASE = """You are an illustrator who draws in SVG. Reply with a single complete SVG document \
and nothing else: no prose, no markdown fence, no explanation.
Rules:
- start with <svg xmlns="http://www.w3.org/2000/svg" and a viewBox
- draw with real geometry: path, rect, circle, ellipse, polygon, line, g
- never embed a raster image, never use <image>, never use <foreignObject>
- no external references, no scripts, no animation
- text is allowed but keep it to short labels"""

# each variant tests one idea, so a win is attributable to something
VARIANTS = {
    "base": BASE,

    "detail": BASE + """

Draw at the density a professional illustration has. A finished drawing is
usually 60 to 200 elements: outlines, fills, interior detail, labels. Ten
shapes is a placeholder, not a drawing.""",

    "plan": """You are an illustrator who draws in SVG.

Before drawing, work out in your head: the canvas size, what sits where, and
what the four or five main parts are. Then draw them one at a time, finishing
each before starting the next.

Reply with a single complete SVG document and nothing else: no prose, no
markdown fence, no explanation.
- start with <svg xmlns="http://www.w3.org/2000/svg" and a viewBox
- draw with real geometry: path, rect, circle, ellipse, polygon, line, g
- group related parts in <g> with an id so the drawing has structure
- never embed a raster image, never use <image>, never use <foreignObject>
- no scripts, no animation. text is allowed for short labels""",

    "craft": BASE + """

What separates a finished drawing from a sketch:
- a deliberate palette, three or four colours that belong together, not defaults
- consistent stroke weight, and a heavier weight for outer edges than interior lines
- real interior detail on every major shape, not just a silhouette
- alignment: things that should line up, line up exactly
- whitespace at the edges, the drawing does not touch the viewBox border""",

    "xml": BASE + """

The output must parse as XML on the first try:
- escape & as &amp; in text, always
- never repeat an attribute on one element
- close every tag""",

    "detail_craft": BASE + """

Draw at the density a professional illustration has. A finished drawing is
usually 60 to 200 elements: outlines, fills, interior detail, labels. Ten
shapes is a placeholder, not a drawing.

What separates a finished drawing from a sketch:
- a deliberate palette, three or four colours that belong together, not defaults
- consistent stroke weight, heavier on outer edges than interior lines
- real interior detail on every major shape, not just a silhouette
- alignment: things that should line up, line up exactly

The output must parse as XML on the first try: escape & as &amp;, never repeat
an attribute, close every tag.""",
}


def generate(provider, system: str, prompt: str, pid: str):
    import bringup.providers as P
    old, P.SYSTEM = P.SYSTEM, system
    try:
        return provider.generate(prompt, pid, timeout=300)
    finally:
        P.SYSTEM = old


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=6, help="prompts per variant")
    ap.add_argument("--jobs", type=int, default=3)
    ap.add_argument("--out", default="runs/evolve")
    ap.add_argument("--variants", default="")
    args = ap.parse_args()

    load_env()
    if not os.environ.get("LOCAL_MODEL"):
        print("set LOCAL_MODEL and start the server: python -m bringup.serve")
        return 1

    provider = OpenAIProvider(
        model=os.environ["LOCAL_MODEL"],
        base_url=os.environ.get("LOCAL_BASE_URL", "http://localhost:8080"),
        api_key_env="LOCAL_API_KEY",
        name="local",
        max_tokens=int(os.environ.get("LOCAL_MAX_TOKENS", "16000")),
    )
    judge = VisionJudge()

    all_prompts = json.loads(PROMPTS.read_text())
    # one from each family, so a variant cannot win by being good at icons only
    fams, picked = {}, []
    for p in all_prompts:
        fams.setdefault(p["family"], []).append(p)
    while len(picked) < args.n:
        for f in sorted(fams):
            if fams[f] and len(picked) < args.n:
                picked.append(fams[f].pop(0))

    names = [v.strip() for v in args.variants.split(",") if v.strip()] or list(VARIANTS)
    out = ROOT / args.out
    out.mkdir(parents=True, exist_ok=True)
    print(f"{len(names)} variants x {len(picked)} prompts, judged against base\n")

    results = {}
    for name in names:
        system = VARIANTS[name]
        d = out / name
        d.mkdir(exist_ok=True)

        def one(p):
            f = d / f"{p['id']}.svg"
            if f.exists():
                return p, f.read_text(), True
            g = generate(provider, system, p["prompt"], p["id"])
            if g.ok:
                f.write_text(g.svg)
            return p, g.svg, False

        rows = []
        with ThreadPoolExecutor(max_workers=args.jobs) as ex:
            for p, svg, cached in ex.map(one, picked):
                ok = False
                info = {}
                if svg:
                    r = check(svg)
                    ok, info = r.passed, r.info
                rows.append({"id": p["id"], "ok": bool(svg), "gates": ok, **info})
        gp = sum(1 for r in rows if r["gates"])
        got = sum(1 for r in rows if r["ok"])
        shapes = [r.get("shapes", 0) for r in rows if r["ok"]]
        byts = [r.get("bytes", 0) for r in rows if r["ok"]]
        results[name] = {"rows": rows, "svg": got, "gates": gp,
                         "shapes": sorted(shapes)[len(shapes)//2] if shapes else 0,
                         "bytes": sorted(byts)[len(byts)//2] if byts else 0}
        print(f"{name:14} svg {got}/{len(picked)}  gates {gp}/{len(picked)}  "
              f"median {results[name]['shapes']:4} shapes  {results[name]['bytes']:6} bytes")

    # gates and size say nothing about quality, so ask the judge directly
    print("\njudged against base, per prompt")
    prompts_by_id = {p["id"]: p for p in picked}
    for name in names:
        if name == "base":
            continue
        wins = losses = ties = skipped = 0
        for p in picked:
            fa, fb = out / "base" / f"{p['id']}.svg", out / name / f"{p['id']}.svg"
            if not (fa.exists() and fb.exists()):
                skipped += 1
                continue
            try:
                a = rasterize(fa.read_text(), width=448)
                b = rasterize(fb.read_text(), width=448)
            except RenderError:
                skipped += 1
                continue
            v = judge.compare(a, b, prompts_by_id[p["id"]]["prompt"])
            if v.error or v.winner in (None, "biased"):
                skipped += 1
            elif v.winner == "b":
                wins += 1
            elif v.winner == "a":
                losses += 1
            else:
                ties += 1
        results[name]["vs_base"] = {"wins": wins, "losses": losses, "ties": ties, "skipped": skipped}
        print(f"  {name:14} beats base {wins}, loses {losses}, neither {ties}, skipped {skipped}")

    (out / "results.json").write_text(json.dumps(results, indent=1))
    print(f"\nwrote {out}/results.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
