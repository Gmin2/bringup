"""Turns generated runs into supervised examples.

Two kinds come out of the same file. A direct example is the prompt and a plan
that passed. A repair example is the prompt, the broken plan the model actually
wrote, the validator's complaint, and the fix. The second kind is only available
because the recorder keeps the attempts compose() throws away, and it is the
part that teaches the model to read an error and act on it.

Nothing dirty is ever used as a target: the assistant turn is always a plan that
scored clean.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PLANS = ROOT / "data/plans"
DATA = ROOT / "data"


@dataclass
class Example:
    kind: str
    source: str
    messages: list[dict]

    def to_json(self) -> str:
        return json.dumps({"kind": self.kind, "source": self.source, "messages": self.messages})


def _system(hash_: str) -> str:
    f = DATA / f"system-{hash_}.txt"
    if not f.exists():
        raise FileNotFoundError(f"missing {f}; regenerate with node/generate.mjs")
    return f.read_text()


def build(plans_dir: Path = PLANS) -> list[Example]:
    out: list[Example] = []
    for f in sorted(plans_dir.glob("*.json")):
        run = json.loads(f.read_text())
        calls = run.get("calls") or []
        if not calls or not run.get("system"):
            continue
        system = _system(run["system"])
        prompt = run["prompt"]["prompt"]

        for i, call in enumerate(calls):
            if not call.get("ok"):
                continue
            if i == 0:
                out.append(
                    Example(
                        "direct",
                        run["id"],
                        [
                            {"role": "system", "content": system},
                            {"role": "user", "content": prompt},
                            {"role": "assistant", "content": call["text"]},
                        ],
                    )
                )
            else:
                prior = calls[i - 1]
                if prior.get("ok"):
                    continue
                out.append(
                    Example(
                        "repair",
                        run["id"],
                        [
                            {"role": "system", "content": system},
                            {"role": "user", "content": prompt},
                            {"role": "assistant", "content": prior["text"]},
                            {"role": "user", "content": call["ask"]},
                            {"role": "assistant", "content": call["text"]},
                        ],
                    )
                )
    return out


def main():
    ex = build()
    kinds = {}
    for e in ex:
        kinds[e.kind] = kinds.get(e.kind, 0) + 1
    out = DATA / "sft.jsonl"
    out.write_text("\n".join(e.to_json() for e in ex) + ("\n" if ex else ""))
    print(f"{len(ex)} examples -> {out}")
    print("by kind:", kinds)
    if ex:
        chars = [sum(len(m["content"]) for m in e.messages) for e in ex]
        print(f"chars per example: min {min(chars)} median {sorted(chars)[len(chars)//2]} max {max(chars)}")


if __name__ == "__main__":
    main()
