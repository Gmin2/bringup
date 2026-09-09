"""Do the gates fire on the cheats they exist for?

Each case below is a specific thing a model will do to score well without
drawing anything. The test asserts the named check fails, not just that the
overall result fails, so a cheat cannot be caught by accident by some other
check while the one meant to catch it quietly never fires.
"""

from __future__ import annotations

import base64
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from bringup.gates import check

CORPUS = Path.home() / "coding/ml/illustrations/solder"

# a real 1x1 png, the smallest possible "just embed a bitmap" cheat
PNG_1PX = base64.b64encode(bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000a49444154789c6360000002000100ffff03000006000557bfabd400"
    "00000049454e44ae426082"
)).decode()

def svg(body: str, vb: str = "0 0 100 100") -> str:
    return f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" viewBox="{vb}">{body}</svg>'

ART = "".join(
    f'<circle cx="{10+i*8}" cy="{20+(i%3)*20}" r="5" fill="#{i*2:02x}5f{9-i:x}0"/>' for i in range(10)
) + '<path d="M5,90 L95,90" stroke="#123" stroke-width="2"/>'

CHEATS = [
    ("embeds a bitmap", "no_raster",
     svg(f'{ART}<image href="data:image/png;base64,{PNG_1PX}" width="100" height="100"/>')),
    ("html in foreignObject", "no_foreign_object",
     svg(f'{ART}<foreignObject width="100" height="100"><div xmlns="http://www.w3.org/1999/xhtml">hi</div></foreignObject>')),
    ("viewBox shrunk to nothing", "viewbox_sane", svg(ART, vb="0 0 4 4")),
    ("viewBox aspect absurd", "viewbox_sane", svg(ART, vb="0 0 4000 30")),
    ("blank canvas", "ink_ok", svg('<rect width="100" height="100" fill="#fff"/>')),
    ("one solid fill", "varied", svg('<rect width="100" height="100" fill="#345"/>')),
    ("too short to be a drawing", "length_ok", svg('<circle cx="50" cy="50" r="9" fill="#333"/>')),
    ("malformed xml", "parses", '<svg viewBox="0 0 10 10"><path d="M0,0'),
    ("not an svg at all", "is_svg", '<html><body>drawing goes here</body></html>'),
]


def main() -> int:
    bad = []

    print("cheats")
    for name, expect, s in CHEATS:
        r = check(s)
        fired = r.checks.get(expect) is False
        ok = fired and not r.passed
        print(f"  {'ok  ' if ok else 'MISS'} {name:28} -> {expect}"
              + ("" if fired else f"   (check reported {r.checks.get(expect)!r})"))
        if not ok:
            bad.append(name)

    print("\ncorpus")
    files = sorted(CORPUS.glob("parts/*.svg")) + sorted(CORPUS.glob("assemblies/*.svg"))
    failed = []
    for f in files:
        r = check(f.read_text())
        if not r.passed:
            failed.append((f.name, r.reasons))
    print(f"  {len(files) - len(failed)}/{len(files)} known-good svgs pass")
    for n, why in failed[:8]:
        print(f"    {n}: {'; '.join(why)}")

    # a gate that rejects real work is as broken as one that lets cheats through
    if len(failed) > len(files) * 0.05:
        bad.append(f"{len(failed)} corpus files rejected")

    print("\n" + ("gates fire on every cheat and accept real drawings"
                  if not bad else f"PROBLEM: {bad}"))
    return 0 if not bad else 1


if __name__ == "__main__":
    raise SystemExit(main())
