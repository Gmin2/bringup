"""Python side of node/score.mjs.

Holds one long-lived node worker and talks JSONL to it, so @solder/core is
imported once instead of per rollout.
"""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


@dataclass
class Score:
    ok: bool
    gate: float
    terms: dict[str, float | None]
    counts: dict[str, list[int]]
    issues: list[dict] = field(default_factory=list)
    cover: dict = field(default_factory=dict)

    def error_msgs(self) -> list[str]:
        return [i["msg"] for i in self.issues if i["level"] == "error"]

    def total(self, weights: dict[str, float]) -> float:
        """Weighted sum over whichever terms the config names. Terms that came
        back None (coverage with no expect list) are dropped and the remaining
        weights renormalised, so a missing term does not silently score zero."""
        used = {k: w for k, w in weights.items() if self.terms.get(k) is not None}
        if not used:
            return 0.0
        norm = sum(used.values())
        return sum(w * self.terms[k] for k, w in used.items()) / norm


class Scorer:
    def __init__(self, root: Path = ROOT, error_cap: int = 6):
        script = root / "node/score.mjs"
        if not script.exists():
            raise FileNotFoundError(script)
        env = {**os.environ, "BRINGUP_ERROR_CAP": str(error_cap)}
        self.proc = subprocess.Popen(
            ["node", "node/score.mjs"],
            cwd=root,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            env=env,
        )
        self._n = 0

    def score(self, plan: dict, expect: list[str] | None = None) -> Score:
        self._n += 1
        self.proc.stdin.write(json.dumps({"id": self._n, "plan": plan, "expect": expect}) + "\n")
        self.proc.stdin.flush()
        line = self.proc.stdout.readline()
        if not line:
            raise RuntimeError(f"scorer died: {self.proc.stderr.read()[-2000:]}")
        r = json.loads(line)
        return Score(
            ok=r.get("ok", False),
            gate=r.get("gate", 0),
            terms=r.get("terms", {}),
            counts=r.get("counts", {}),
            issues=r.get("issues", []),
            cover=r.get("cover", {}),
        )

    def close(self):
        try:
            self.proc.stdin.close()
            self.proc.wait(timeout=5)
        except Exception:
            self.proc.kill()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()
