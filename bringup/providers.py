"""One interface over every model in the comparison.

Prompt in, SVG text out. The differences between a chat model that happens to
write SVG and a dedicated SVG endpoint are absorbed here so the arena does not
have to care which is which.

Nothing is scored in this file. Providers return whatever the model actually
said, including malformed output, because "it returned something that is not an
svg" is a result the comparison needs to show rather than hide.
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# an <svg> anywhere in the reply, fenced or not. chat models wrap it in prose
# and code fences roughly half the time.
_SVG = re.compile(r"<svg\b.*?</svg\s*>", re.S | re.I)

SYSTEM = (
    "You are an illustrator who draws in SVG. Reply with a single complete SVG document "
    "and nothing else: no prose, no markdown fence, no explanation.\n"
    "Rules:\n"
    "- start with <svg xmlns=\"http://www.w3.org/2000/svg\" and a viewBox\n"
    "- draw with real geometry: path, rect, circle, ellipse, polygon, line, g\n"
    "- never embed a raster image, never use <image>, never use <foreignObject>\n"
    "- no external references, no scripts, no animation\n"
    "- text is allowed but keep it to short labels"
)


def load_env(path: Path = ROOT / ".env") -> None:
    """Minimal .env reader so there is no dependency for four lines of parsing."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


@dataclass
class Generation:
    provider: str
    model: str
    prompt_id: str
    svg: str | None = None
    raw: str = ""
    ms: int = 0
    error: str | None = None
    usage: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.svg is not None


def extract_svg(text: str) -> str | None:
    m = _SVG.search(text or "")
    return m.group(0) if m else None


def _post(url: str, body: dict, headers: dict, timeout: int) -> dict:
    req = urllib.request.Request(
        url, data=json.dumps(body).encode(), headers={"content-type": "application/json", **headers}
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


class OpenAIProvider:
    """A chat model asked to write SVG. Also serves any openai-compatible
    endpoint, which is how our own model joins the comparison later."""

    def __init__(self, model: str | None = None, base_url: str | None = None,
                 api_key_env: str = "OPENAI_API_KEY", name: str = "openai"):
        self.name = name
        self.model = model or os.environ.get("OPENAI_MODEL", "gpt-6-astra")
        self.base = (base_url or os.environ.get("OPENAI_BASE_URL", "https://api.openai.com")).rstrip("/")
        self.key = os.environ.get(api_key_env, "")

    def generate(self, prompt: str, prompt_id: str = "", timeout: int = 180) -> Generation:
        g = Generation(self.name, self.model, prompt_id)
        if not self.key:
            g.error = "no api key"
            return g
        t0 = time.perf_counter()
        try:
            d = _post(
                f"{self.base}/v1/chat/completions",
                {
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": SYSTEM},
                        {"role": "user", "content": prompt},
                    ],
                },
                {"authorization": f"Bearer {self.key}"},
                timeout,
            )
            g.raw = d["choices"][0]["message"]["content"] or ""
            g.svg = extract_svg(g.raw)
            u = d.get("usage") or {}
            g.usage = {"in": u.get("prompt_tokens", 0), "out": u.get("completion_tokens", 0)}
            if g.svg is None:
                g.error = "no <svg> in the reply"
        except urllib.error.HTTPError as e:
            g.error = f"http {e.code}: {e.read()[:200].decode(errors='replace')}"
        except Exception as e:
            g.error = f"{type(e).__name__}: {e}"
        g.ms = int((time.perf_counter() - t0) * 1000)
        return g


class QuiverProvider:
    """A dedicated SVG endpoint, so no extraction guesswork: the svg arrives at
    data[0].svg. https://docs.quiver.ai/api"""

    def __init__(self, model: str | None = None, base_url: str | None = None):
        self.name = "quiver"
        self.model = model or os.environ.get("QUIVER_MODEL", "arrow-1.1")
        self.base = (base_url or os.environ.get("QUIVER_BASE_URL", "https://api.quiver.ai")).rstrip("/")
        self.key = os.environ.get("QUIVER_API_KEY", "")

    def generate(self, prompt: str, prompt_id: str = "", timeout: int = 180) -> Generation:
        g = Generation(self.name, self.model, prompt_id)
        if not self.key:
            g.error = "no api key"
            return g
        t0 = time.perf_counter()
        try:
            d = _post(
                f"{self.base}/v1/svgs/generations",
                {"model": self.model, "prompt": prompt, "n": 1, "stream": False},
                {"authorization": f"Bearer {self.key}"},
                timeout,
            )
            data = d.get("data") or []
            g.raw = data[0].get("svg", "") if data else json.dumps(d)[:2000]
            g.svg = extract_svg(g.raw) or (g.raw if g.raw.lstrip().startswith("<svg") else None)
            g.usage = {"credits": d.get("credits", 0)}
            if g.svg is None:
                g.error = "no svg in data[]"
        except urllib.error.HTTPError as e:
            body = e.read()[:300].decode(errors="replace")
            g.error = f"http {e.code}: {body}"
        except Exception as e:
            g.error = f"{type(e).__name__}: {e}"
        g.ms = int((time.perf_counter() - t0) * 1000)
        return g


def available() -> list:
    """Whichever providers have a key. A missing key is a skipped column, not a
    crash, so the arena still runs with only one model configured."""
    load_env()
    out = []
    if os.environ.get("OPENAI_API_KEY"):
        out.append(OpenAIProvider())
    if os.environ.get("QUIVER_API_KEY"):
        out.append(QuiverProvider())
    if os.environ.get("LOCAL_MODEL"):
        out.append(OpenAIProvider(
            model=os.environ["LOCAL_MODEL"],
            base_url=os.environ.get("LOCAL_BASE_URL", "http://localhost:8000"),
            api_key_env="LOCAL_API_KEY",
            name="local",
        ))
    return out
