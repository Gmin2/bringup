"""Build a training prompt set, grounded in real subject matter.

The 34 hand-written prompts are the eval and are never trained on. This makes
the training prompts, drawn from subjects the corpus actually contains: the 123
tailark illustration names for product-ui, the solder catalog for hardware, and
short noun lists for icons and logos.

Grounding matters more than volume. A prompt for "an ai memory panel" describes
a thing we have a reference drawing of, so the output can be judged against
something real later. Prompts invented from nothing cannot be.

    python -m bringup.genprompts --n 500 --out data/illus/train_prompts.json
"""

from __future__ import annotations

import argparse
import json
import random
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CORPUS = Path.home() / "coding/ml/illustrations"
HELD_OUT = ROOT / "data/illus/prompts.json"

STYLE_UI = [
    "soft rounded cards, subtle depth, muted palette",
    "clean minimal ui, thin borders, restrained colour",
    "rounded panel on a pale ground, one accent colour",
    "flat cards, generous whitespace, small type",
    "light shadows, rounded corners, two-tone",
]
# verb and style are paired, not sampled independently: "a wiring diagram in an
# isometric exploded view" is a contradiction, and a teacher asked to draw one
# produces confused output that is worse than no training example at all.
HW_BRIEFS = [
    ("an isometric exploded technical drawing of",
     "thin blue line work on an off-white ground, monospace labels, leader lines"),
    ("an isometric exploded technical drawing of",
     "blueprint style, dimension lines, numbered callouts, pale paper"),
    ("a wiring diagram of",
     "rounded boxes joined by orthogonal wires, pin names, dashed power rails"),
    ("a wiring diagram of",
     "flat schematic, thin blue lines on white, monospace pin labels"),
    ("a flat technical schematic of",
     "ink outlines, flat fills, hatched faces, a callout with a leader arrow"),
    ("a cutaway technical drawing of",
     "thin outlines, interior detail visible, labelled layers"),
]
STYLE_SCENE = [
    "small isometric scene, pale ground plane, soft shadows",
    "thin outlines, minimal palette, gentle depth",
    "flat vector scene, two accent colours",
]
STYLE_ICON = [
    "single accent colour, rounded corners, no text",
    "uniform stroke width, rounded caps, line icon",
    "flat two tone, simple geometry",
]

VERB_UI = ["a product illustration of", "a ui illustration showing", "an interface illustration of"]
VERB_SC = ["a small isometric scene of", "an illustration of", "a minimal scene showing"]

ICONS = """folder document cloud chart lock bell gear search filter calendar clock mail
inbox tag bookmark heart star download upload share link trash edit camera image video
mic speaker wifi battery plug shield key user users home settings grid list map pin
compass rocket flag bug database server terminal branch commit package box truck cart
card wallet receipt graph pulse target layers palette brush pen ruler scissors""".split()

LOGO_SHAPES = """circle triangle hexagon arc spiral wave orbit ring lattice prism knot
chevron droplet leaf flame crystal loop helix grid arrow""".split()


def art(w: str) -> str:
    return ("an " if w[:1].lower() in "aeiou" else "a ") + w


def words(slug: str) -> str:
    s = re.sub(r"[-_]+", " ", slug)
    s = re.sub(r"\b(\d+)\b", r"\1", s)
    return s.strip()


def load_subjects():
    ui, hw, parts = [], [], []
    m = CORPUS / "tailark/manifest.json"
    if m.exists():
        ui = [words(i["name"]) for i in json.loads(m.read_text())["items"]]
    a = CORPUS / "solder/assemblies"
    if a.exists():
        hw = sorted({words(p.stem.replace("asm-", "")) for p in a.glob("*.svg")})
    p = CORPUS / "solder/parts"
    if p.exists():
        parts = [words(x.stem) for x in p.glob("*.svg")]
    return ui, hw, parts


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=500)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--out", default="data/illus/train_prompts.json")
    args = ap.parse_args()

    rng = random.Random(args.seed)
    ui, hw, parts = load_subjects()
    held = {p["prompt"].strip().lower() for p in json.loads(HELD_OUT.read_text())}

    def gen():
        fam = rng.choices(
            ["product-ui", "scene", "hardware", "icon", "logo"],
            weights=[34, 24, 22, 12, 8],
        )[0]
        if fam == "product-ui" and ui:
            return fam, f"{rng.choice(VERB_UI)} {rng.choice(ui)}, {rng.choice(STYLE_UI)}"
        if fam == "scene" and ui:
            return fam, f"{rng.choice(VERB_SC)} {rng.choice(ui)}, {rng.choice(STYLE_SCENE)}"
        if fam == "hardware" and (hw or parts):
            if hw and rng.random() < 0.6:
                subj = rng.choice(hw)
            else:
                subj = " and ".join(art(x) for x in rng.sample(parts, min(2, len(parts))))
            verb, style = rng.choice(HW_BRIEFS)
            return fam, f"{verb} {subj}, {style}"
        if fam == "logo":
            a, b = rng.sample(LOGO_SHAPES, 2)
            style = rng.choice([x for x in STYLE_ICON if "no text" not in x])
            return fam, f"a geometric logo mark built from {art(a)} and {art(b)}, {style}, no text"
        w = rng.choice(ICONS)
        return "icon", f"an icon of {art(w)}, {rng.choice(STYLE_ICON)}"

    seen, out = set(), []
    guard = 0
    while len(out) < args.n and guard < args.n * 60:
        guard += 1
        fam, text = gen()
        k = text.strip().lower()
        if k in seen or k in held:
            continue
        seen.add(k)
        out.append({"id": f"tr-{len(out):05d}", "family": fam, "prompt": text})

    Path(args.out).write_text(json.dumps(out, indent=1))
    from collections import Counter
    print(f"{len(out)} prompts -> {args.out}")
    print("by family:", dict(Counter(p["family"] for p in out)))
    print("held-out eval prompts excluded:", len(held))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
