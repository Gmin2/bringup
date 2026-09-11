"""Stop Qwen's chat template training an empty think block into every example.

The template emits `<|im_start|>assistant\n<think>\n\n</think>\n\n` before the
content whenever the assistant turn is last, even with no reasoning content. At
inference the generation prompt stops at `assistant\n`, so the model has to
produce those think tokens itself, and the first fine-tune learned to open with
mangled template markup (`</tool_call>`, once a Thai word) instead of `<svg`.

Narrowing the condition to `reasoning_content` makes an empty one fall through
to the plain branch, so training and inference agree.

This edits a file in the HF cache, which a re-download would revert, so it lives
here as a script and is idempotent.

    python -m bringup.patch_template [--revert]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODEL = "models--mlx-community--Qwen3-4B-Instruct-2507-4bit"
OLD = "{%- if loop.last or (not loop.last and reasoning_content) %}"
NEW = "{%- if reasoning_content %}"


def template_path() -> Path:
    snaps = sorted((ROOT / "tmp/hf/hub" / MODEL / "snapshots").glob("*/chat_template.jinja"))
    if not snaps:
        raise FileNotFoundError("no chat_template.jinja in the local hf cache")
    return snaps[0]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--revert", action="store_true")
    args = ap.parse_args()

    p = template_path()
    bak = p.with_suffix(".jinja.orig")
    text = p.read_text()

    if args.revert:
        if not bak.exists():
            print("no backup to revert to"); return 1
        p.write_text(bak.read_text()); print(f"reverted {p}"); return 0

    if NEW in text and OLD not in text:
        print(f"already patched: {p}"); return 0
    if OLD not in text:
        print(f"pattern not found, template may have changed:\n  {OLD}"); return 1

    if not bak.exists():
        bak.write_text(text)
    p.write_text(text.replace(OLD, NEW, 1))
    print(f"patched {p}\n  backup at {bak.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
