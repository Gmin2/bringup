"""SVG text -> numpy array, via resvg.

This is the reward's eyes, so it has to give the same pixels on a laptop and on
the training box. Fonts are the only part of resvg that is not already
deterministic: it resolves family names against whatever is installed. So we
ship two font files, tell resvg to ignore system fonts entirely, and rewrite
every font-family in the SVG down to one of two generic names it can map.

That rewrite is part of the canonical render path, which means it must be
applied to model output and to reference targets alike. Render anything through
`rasterize` and nothing else.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import resvg_py
from PIL import Image

FONT_DIR = Path(__file__).resolve().parent.parent / "fonts"


@dataclass(frozen=True)
class FontConfig:
    files: tuple[str, ...] = ()
    sans: str | None = None
    mono: str | None = None
    skip_system: bool = False

    @property
    def deterministic(self) -> bool:
        return self.skip_system and bool(self.files)


# DejaVu Sans Mono is what Menlo derives from, so pinning it barely moves the
# text compared to what the harness playground shows.
BUNDLED = FontConfig(
    files=tuple(str(FONT_DIR / n) for n in (
        "DejaVuSans.ttf",
        "DejaVuSans-Bold.ttf",
        "DejaVuSansMono.ttf",
        "DejaVuSansMono-Bold.ttf",
    )),
    sans="DejaVu Sans",
    mono="DejaVu Sans Mono",
    skip_system=True,
)

SYSTEM = FontConfig()

_FAMILY = re.compile(r'font-family\s*=\s*"([^"]*)"')
# stop at a rule/brace/tag boundary too: css inside a <style> block often has
# no trailing semicolon, and a greedy class would swallow the rest of the sheet
_FAMILY_CSS = re.compile(r"font-family\s*:\s*([^;{}<\"']+)")


def _generic(stack: str) -> str:
    return "monospace" if "mono" in stack.lower() else "sans-serif"


def canonical_fonts(svg: str) -> str:
    """Collapse every font stack to `monospace` or `sans-serif`.

    resvg maps those two through its generic-family options; it cannot map
    `ui-monospace` or `SFMono-Regular`, and with system fonts skipped an
    unmatched name falls back to the default family, which would silently
    render mono labels in the sans face.
    """
    svg = _FAMILY.sub(lambda m: f'font-family="{_generic(m.group(1))}"', svg)
    return _FAMILY_CSS.sub(lambda m: f"font-family:{_generic(m.group(1))}", svg)


class RenderError(Exception):
    pass


def rasterize(
    svg: str,
    width: int | None = None,
    height: int | None = None,
    background: str = "#ffffff",
    fonts: FontConfig = BUNDLED,
) -> np.ndarray:
    """Return an (H, W, 3) uint8 array. Alpha is flattened onto background."""
    if fonts.skip_system:
        svg = canonical_fonts(svg)

    kwargs: dict = {"svg_string": svg, "background": background}
    if width:
        kwargs["width"] = width
    if height:
        kwargs["height"] = height
    if fonts.skip_system:
        kwargs["skip_system_fonts"] = True
    if fonts.files:
        kwargs["font_files"] = list(fonts.files)
    if fonts.sans:
        kwargs["sans_serif_family"] = fonts.sans
    if fonts.mono:
        kwargs["monospace_family"] = fonts.mono

    try:
        png = resvg_py.svg_to_bytes(**kwargs)
    except Exception as e:
        raise RenderError(str(e)) from e

    if isinstance(png, list):
        png = bytes(png)
    img = Image.open(io.BytesIO(png)).convert("RGB")
    return np.asarray(img, dtype=np.uint8)


def save_png(arr: np.ndarray, path: str | Path) -> None:
    Image.fromarray(arr).save(path)
