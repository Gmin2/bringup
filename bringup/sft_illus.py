"""Turn arena outputs into a training set for mlx_lm.lora.

Only drawings that passed every gate become examples. A training set is the one
place where "it rendered" is not good enough: a broken example teaches the
broken thing, and there is no reward signal downstream to unteach it.

The system prompt stored with each example is the one the student will see at
inference. If those differ the model is trained for a context it never gets.

    python -m bringup.sft_illus --runs sft-pilot --out data/illus/sft
"""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

from bringup.providers import SYSTEM

ROOT = Path(__file__).resolve().parent.parent


def collect(run_dirs: list[Path], prompts: dict) -> list[dict]:
    out = []
    for d in run_dirs:
        for meta in sorted(d.glob("*.json")):
            if meta.name == "rows.json":
                continue
            svg = meta.with_suffix(".svg")
            if not svg.exists():
                continue
            m = json.loads(meta.read_text())
            if not m.get("ok") or not (m.get("gates") or {}).get("passed"):
                continue
            pid = m["id"]
            if pid not in prompts:
                continue
            out.append({
                "messages": [
                    {"role": "system", "content": SYSTEM},
                    {"role": "user", "content": prompts[pid]["prompt"]},
                    {"role": "assistant", "content": svg.read_text().strip()},
                ],
                "_id": pid,
                "_family": m.get("family", "?"),
                "_bytes": m["info"]["bytes"],
            })
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", default="sft-pilot", help="comma separated run names")
    ap.add_argument("--prompts", default="data/illus/train_prompts.json")
    ap.add_argument("--out", default="data/illus/sft")
    ap.add_argument("--valid", type=float, default=0.1)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--max-tokens", type=int, default=0,
                    help="drop examples longer than this. dropping loses an example, "
                         "truncating corrupts one: a cut svg never closes its tag, and "
                         "training on that teaches exactly the failure we are trying to fix")
    args = ap.parse_args()

    prompts = {p["id"]: p for p in json.loads((ROOT / args.prompts).read_text())}
    dirs = [ROOT / "runs" / r.strip() / "openai" for r in args.runs.split(",")]
    rows = collect([d for d in dirs if d.exists()], prompts)
    if args.max_tokens:
        import os
        os.environ.setdefault("HF_HOME", str(ROOT / "tmp/hf"))
        os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
        from transformers import AutoTokenizer
        tok = AutoTokenizer.from_pretrained(
            os.environ.get("LOCAL_MODEL", "mlx-community/Qwen3-4B-Instruct-2507-4bit"))
        def ntokens(msgs) -> int:
            # apply_chat_template returns a BatchEncoding in current transformers,
            # so len() gives the number of keys (2) rather than the token count.
            # that silently passed every length filter until it was checked.
            out = tok.apply_chat_template(msgs, tokenize=True)
            if isinstance(out, dict) or hasattr(out, "input_ids"):
                out = out["input_ids"]
            if out and isinstance(out[0], list):
                out = out[0]
            return len(out)

        kept = []
        for r in rows:
            n = ntokens(r["messages"])
            r["_tokens"] = n
            if n <= args.max_tokens:
                kept.append(r)
        print(f"token filter at {args.max_tokens}: kept {len(kept)}/{len(rows)}, "
              f"dropped {len(rows) - len(kept)} rather than truncate them")
        rows = kept
    if not rows:
        print("nothing collected")
        return 1

    # split by family so a small valid set still covers every kind of drawing
    rng = random.Random(args.seed)
    byfam: dict[str, list] = {}
    for r in rows:
        byfam.setdefault(r["_family"], []).append(r)
    train, valid = [], []
    for fam, g in sorted(byfam.items()):
        rng.shuffle(g)
        k = max(1, int(len(g) * args.valid))
        valid += g[:k]
        train += g[k:]
    rng.shuffle(train)

    out = ROOT / args.out
    out.mkdir(parents=True, exist_ok=True)
    for name, rows_ in (("train", train), ("valid", valid)):
        with open(out / f"{name}.jsonl", "w") as f:
            for r in rows_:
                f.write(json.dumps({"messages": r["messages"]}) + "\n")

    from collections import Counter
    print(f"{len(rows)} examples -> {out}  (train {len(train)}, valid {len(valid)})")
    print("by family:", dict(Counter(r["_family"] for r in rows)))
    b = sorted(r["_bytes"] for r in rows)
    print(f"svg bytes: min {b[0]} median {b[len(b)//2]} max {b[-1]}")
    chars = sorted(sum(len(m["content"]) for m in r["messages"]) for r in rows)
    print(f"example chars: median {chars[len(chars)//2]} max {chars[-1]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
