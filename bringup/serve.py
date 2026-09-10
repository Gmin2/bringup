"""Serve a local model through mlx, OpenAI-compatible.

The point of measuring locally rather than through an aggregator is that the
model we test is byte for byte the model we would train: no provider-side
quantisation, no serving differences, no rate limits.

    python -m bringup.serve --model mlx-community/Qwen3-4B-Instruct-2507-4bit

Then point the arena at it:

    LOCAL_BASE_URL=http://localhost:8080 LOCAL_MODEL=qwen3-4b \\
      python -m bringup.arena --providers local
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

DEFAULT = "mlx-community/Qwen3-4B-Instruct-2507-4bit"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=DEFAULT)
    ap.add_argument("--port", type=int, default=8080)
    args = ap.parse_args()

    env = {
        **os.environ,
        "HF_HOME": str(ROOT / "tmp/hf"),
        # the xet transfer path stalls partway through large downloads
        "HF_HUB_DISABLE_XET": "1",
    }
    cmd = [sys.executable, "-m", "mlx_lm", "server", "--model", args.model, "--port", str(args.port)]
    print(" ".join(cmd))
    return subprocess.call(cmd, env=env)


if __name__ == "__main__":
    raise SystemExit(main())
