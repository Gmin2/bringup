"""A vision model asked which of two drawings is better.

Same question the rating page asks a person, so the answers are directly
comparable and the judge can be checked against real ratings before it is
trusted with anything.

Two things it does deliberately:

  - pairwise, never a score out of ten. surya's post-mortem found absolute
    scores bunch near the bottom and leave the reward almost no dynamic range.
  - each pair is asked twice with the images swapped. a judge that answers
    "left" both times has a position bias, and counting that as agreement would
    inflate every number downstream.
"""

from __future__ import annotations

import base64
import io
import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

import numpy as np
from PIL import Image

PROMPT = """Two attempts at the same drawing brief. Which is better?

Brief: {brief}

Judge on: does it show what the brief asks for, is the composition deliberate,
is the detail real rather than filler, would a designer ship it.

Answer with one word only: A, B, or NEITHER. Use NEITHER only if both fail the
brief badly."""


def _b64(arr: np.ndarray) -> str:
    buf = io.BytesIO()
    Image.fromarray(arr).save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


@dataclass
class Verdict:
    winner: str | None      # "a", "b", "neither", or None on failure
    raw: str = ""
    ms: int = 0
    error: str | None = None


class VisionJudge:
    def __init__(self, model: str | None = None, base_url: str | None = None,
                 api_key_env: str = "OPENAI_API_KEY"):
        self.model = model or os.environ.get("JUDGE_MODEL", "gpt-6-astra")
        self.base = (base_url or os.environ.get("JUDGE_BASE_URL", "https://api.openai.com")).rstrip("/")
        self.key = os.environ.get(api_key_env, "")
        self.token_param = ("max_completion_tokens" if "api.openai.com" in self.base
                            else "max_tokens")

    def _ask(self, a: np.ndarray, b: np.ndarray, brief: str, timeout: int,
             tries: int = 2) -> Verdict:
        v = Verdict(None)
        if not self.key:
            v.error = "no api key"
            return v
        body = {
            "model": self.model,
            self.token_param: 16,
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "text", "text": PROMPT.format(brief=brief)},
                    {"type": "text", "text": "A:"},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{_b64(a)}"}},
                    {"type": "text", "text": "B:"},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{_b64(b)}"}},
                ],
            }],
        }
        t0 = time.perf_counter()
        try:
            req = urllib.request.Request(
                f"{self.base}/v1/chat/completions",
                data=json.dumps(body).encode(),
                headers={"content-type": "application/json", "authorization": f"Bearer {self.key}"},
            )
            with urllib.request.urlopen(req, timeout=timeout) as r:
                d = json.loads(r.read())
            choice = d["choices"][0]
            v.raw = (choice["message"]["content"] or "").strip()
            t = v.raw.upper()
            v.winner = "a" if t.startswith("A") else "b" if t.startswith("B") else "neither" if "N" in t else None
            if v.winner is None:
                # an empty reply is usually the model spending its budget on a
                # reasoning preamble, not a refusal. say which so it is fixable.
                v.error = (f"empty reply (finish_reason={choice.get('finish_reason')})"
                           if not v.raw else f"unparsable: {v.raw[:60]}")
        except urllib.error.HTTPError as e:
            v.error = f"http {e.code}: {e.read()[:200].decode(errors='replace')}"
        except Exception as e:
            v.error = f"{type(e).__name__}: {e}"
        v.ms = int((time.perf_counter() - t0) * 1000)
        if v.winner is None and tries > 1:
            again = self._ask(a, b, brief, timeout, tries - 1)
            again.ms += v.ms
            return again
        return v

    def compare(self, a: np.ndarray, b: np.ndarray, brief: str, timeout: int = 120) -> Verdict:
        """Ask both ways round. Disagreement means position bias, not a tie, so
        it is reported as such rather than folded into the result."""
        first = self._ask(a, b, brief, timeout)
        if first.error:
            return first
        second = self._ask(b, a, brief, timeout)
        if second.error:
            return second

        flip = {"a": "b", "b": "a", "neither": "neither"}
        agreed = flip.get(second.winner) == first.winner
        v = Verdict(
            first.winner if agreed else "biased",
            raw=f"{first.raw}|{second.raw}",
            ms=first.ms + second.ms,
        )
        return v
