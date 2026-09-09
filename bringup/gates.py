"""The free checks. No model, no target image, no judge.

With text conditioning there is nothing to compare the output against, so these
carry more weight than they would otherwise: they are the only part of the
reward that cannot be argued with. Most of them exist because of a specific
cheat a model will otherwise find.

Every check returns a named result. Nothing here collapses to one number.
"""

from __future__ import annotations

import base64
import re
from dataclasses import dataclass, field
from xml.etree import ElementTree

import numpy as np

from bringup.render import RenderError, rasterize

# an svg that is 2% ink is probably blank, one that is 99% ink is a filled
# rectangle. both score well on "looks like the prompt" to a weak judge.
INK_MIN, INK_MAX = 0.004, 0.92
# calibrated against the corpus rather than guessed: real drawings run 1.6KB to
# 75KB with a 7.5KB median, and 5 to 407 shapes. The caps sit well above the
# real ceiling so they only catch runaway generation, not detailed work.
LEN_MIN, LEN_MAX = 200, 150_000
PATH_MIN, PATH_MAX = 1, 4000
ASPECT_MAX = 12.0
VIEWBOX_MIN = 16.0

_RASTER_HREF = re.compile(r'(?:xlink:)?href\s*=\s*["\']\s*data:image/(png|jpe?g|gif|webp|bmp)', re.I)
_VIEWBOX = re.compile(r'viewBox\s*=\s*["\']([^"\']+)["\']')


@dataclass
class GateResult:
    passed: bool
    checks: dict[str, bool] = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)
    info: dict[str, float] = field(default_factory=dict)

    @property
    def value(self) -> float:
        return 1.0 if self.passed else 0.0


def ink_fraction(arr: np.ndarray, tol: int = 16) -> float:
    """Fraction of the canvas that differs from the background.

    Measured against the modal colour, not against white. A drawing on a cream
    or dark ground is still a drawing, and comparing to white called those 100%
    ink and rejected them. A canvas flooded with one colour has no modal
    contrast and correctly comes out near zero.
    """
    flat = arr.reshape(-1, 3)
    # quantise before counting so antialiasing does not split the background
    # into thousands of near-identical shades and hide the real mode
    q = (flat // 8).astype(np.uint16)
    keys = (q[:, 0].astype(np.uint32) << 16) | (q[:, 1].astype(np.uint32) << 8) | q[:, 2]
    vals, counts = np.unique(keys, return_counts=True)
    bg_key = vals[counts.argmax()]
    bg = np.array([(bg_key >> 16) & 0xFF, (bg_key >> 8) & 0xFF, bg_key & 0xFF], dtype=np.int16) * 8 + 4
    dist = np.abs(flat.astype(np.int16) - bg).max(axis=1)
    return float((dist > tol).mean())


def _fail(res: GateResult, name: str, why: str) -> None:
    res.checks[name] = False
    res.reasons.append(why)


def check(svg: str, render_width: int = 384) -> GateResult:
    res = GateResult(passed=False)

    # 1. is it even xml
    try:
        root = ElementTree.fromstring(svg)
    except ElementTree.ParseError as e:
        _fail(res, "parses", f"not well-formed xml: {e}")
        return res
    res.checks["parses"] = True

    tag = root.tag.rsplit("}", 1)[-1]
    if tag != "svg":
        _fail(res, "is_svg", f"root element is <{tag}>, not <svg>")
        return res
    res.checks["is_svg"] = True

    tags = [el.tag.rsplit("}", 1)[-1] for el in root.iter()]

    # 2. no embedding a bitmap and calling it a drawing. this is the cheat that
    #    wins every pixel metric while producing zero vector geometry.
    if "image" in tags or _RASTER_HREF.search(svg):
        _fail(res, "no_raster", "embeds a raster image")
    else:
        res.checks["no_raster"] = True

    # 3. resvg has no html engine, so foreignObject renders blank. a model that
    #    learns to emit it is writing something that only looks right in a browser.
    if "foreignObject" in tags:
        _fail(res, "no_foreign_object", "uses foreignObject, which does not render")
    else:
        res.checks["no_foreign_object"] = True

    # 4. viewBox games. shrinking it is a documented RLRF reward hack: the
    #    drawing scales down until the canvas is near-empty and cheap to match.
    m = _VIEWBOX.search(svg)
    if m:
        try:
            _, _, w, h = [float(x) for x in re.split(r"[\s,]+", m.group(1).strip())]
        except ValueError:
            w = h = 0.0
        res.info["vb_w"], res.info["vb_h"] = w, h
        if w < VIEWBOX_MIN or h < VIEWBOX_MIN:
            _fail(res, "viewbox_sane", f"viewBox {w:g}x{h:g} is degenerate")
        elif max(w, h) / max(1e-6, min(w, h)) > ASPECT_MAX:
            _fail(res, "viewbox_sane", f"viewBox aspect {max(w,h)/min(w,h):.1f} is extreme")
        else:
            res.checks["viewbox_sane"] = True
    else:
        res.checks["viewbox_sane"] = True  # no viewBox is legal, width/height carry it

    # 5. length and geometry budgets, both directions
    n = len(svg)
    res.info["bytes"] = n
    res.checks["length_ok"] = LEN_MIN <= n <= LEN_MAX
    if not res.checks["length_ok"]:
        res.reasons.append(f"{n} bytes, want {LEN_MIN} to {LEN_MAX}")

    drawables = sum(1 for t in tags if t in ("path", "rect", "circle", "ellipse", "polygon", "polyline", "line"))
    res.info["shapes"] = drawables
    res.checks["shapes_ok"] = PATH_MIN <= drawables <= PATH_MAX
    if not res.checks["shapes_ok"]:
        res.reasons.append(f"{drawables} drawable elements, want {PATH_MIN} to {PATH_MAX}")

    # 6. does it actually render, and to something that is neither blank nor solid
    try:
        arr = rasterize(svg, width=render_width)
    except RenderError as e:
        _fail(res, "renders", f"resvg refused it: {e}")
        return res
    res.checks["renders"] = True

    ink = ink_fraction(arr)
    res.info["ink"] = round(ink, 4)
    res.checks["ink_ok"] = INK_MIN <= ink <= INK_MAX
    if not res.checks["ink_ok"]:
        res.reasons.append(f"ink coverage {ink:.3f}, want {INK_MIN} to {INK_MAX}")

    # not one flat colour: a single filled rect passes everything above
    res.info["colours"] = int(len(np.unique(arr.reshape(-1, 3), axis=0)))
    res.checks["varied"] = res.info["colours"] >= 3
    if not res.checks["varied"]:
        res.reasons.append(f"only {res.info['colours']} distinct colours")

    res.passed = all(res.checks.values())
    return res
