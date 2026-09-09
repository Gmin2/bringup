"""Is the render path reproducible, and are the pinned fonts really being used?

Three questions, because a font pin that silently falls back looks identical to
one that works until you run it on a different machine.

  1. does every file in the corpus render without error
  2. is a repeated render byte-identical
  3. does removing the font files change the output on text-bearing files
     (if not, the files were never being used and the pin is decorative)
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from bringup.render import BUNDLED, SYSTEM, FontConfig, RenderError, rasterize

CORPUS = Path.home() / "coding/ml/illustrations/solder"
NO_FILES = FontConfig(sans="DejaVu Sans", mono="DejaVu Sans Mono", skip_system=True)


def digest(a: np.ndarray) -> str:
    return hashlib.sha256(a.tobytes()).hexdigest()[:16]


def main() -> int:
    files = sorted(CORPUS.glob("parts/*.svg")) + sorted(CORPUS.glob("assemblies/*.svg"))
    print(f"{len(files)} svgs\n")

    failed, unstable, text_files, unchanged = [], [], [], []
    for f in files:
        svg = f.read_text()
        has_text = "<text" in svg
        try:
            a = rasterize(svg, width=512, fonts=BUNDLED)
            b = rasterize(svg, width=512, fonts=BUNDLED)
        except RenderError as e:
            failed.append((f.name, str(e)[:70]))
            continue
        if digest(a) != digest(b):
            unstable.append(f.name)
        if has_text:
            text_files.append(f.name)
            try:
                c = rasterize(svg, width=512, fonts=NO_FILES)
                if digest(c) == digest(a):
                    unchanged.append(f.name)
            except RenderError:
                pass  # refusing to render with no fonts is a fine outcome

    print(f"rendered      {len(files) - len(failed)}/{len(files)}   failed {len(failed)}")
    for n, e in failed[:5]:
        print(f"  FAIL {n}: {e}")
    print(f"stable        {len(files) - len(failed) - len(unstable)}/{len(files) - len(failed)}   unstable {len(unstable)}")
    for n in unstable[:5]:
        print(f"  UNSTABLE {n}")
    print(f"text-bearing  {len(text_files)}")
    print(f"  changed when the font files are removed: {len(text_files) - len(unchanged)}/{len(text_files)}")
    if unchanged:
        print(f"  UNUSED on {len(unchanged)} files, e.g. {unchanged[:3]}")

    ok = not failed and not unstable and not unchanged
    print("\n" + ("pinned render path is deterministic and the fonts are in use"
                  if ok else "PROBLEM: see above"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
