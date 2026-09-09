"""Did the model draw what was asked for?

CLIP similarity between the rendered svg and the prompt. This is the only
prompt-adherence signal cheap enough to run inside an RL loop, where every
rollout needs scoring thousands of times per step.

Be clear about what it is: a coarse instrument. It catches "drew a folder when
asked for a calendar". It does not catch a calendar whose day numbers repeat, or
a folder missing the document the prompt named. Those are compositional and
counting failures, and CLIP is weak at exactly those. Treat this as a floor, not
a measure of quality.
"""

from __future__ import annotations

import functools
import os
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import torch
from PIL import Image

MODEL = "ViT-B-32"
PRETRAINED = "laion2b_s34b_b79k"

# keep the weights inside the project. the default ~/.cache/huggingface is not
# always writable, and a cache that silently lives outside the repo is a
# reproducibility problem anyway.
os.environ.setdefault("HF_HOME", str(Path(__file__).resolve().parent.parent / "tmp/hf"))

# the xet transfer path stalls partway through the weight download and leaves a
# held lock behind. plain https pulls the same file at full speed.
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")


def device() -> str:
    if torch.backends.mps.is_available():
        return "mps"
    return "cuda" if torch.cuda.is_available() else "cpu"


@functools.lru_cache(maxsize=1)
def _load(model: str = MODEL, pretrained: str = PRETRAINED):
    import open_clip

    dev = device()
    net, _, preprocess = open_clip.create_model_and_transforms(model, pretrained=pretrained)
    net = net.to(dev).eval()
    tok = open_clip.get_tokenizer(model)
    return net, preprocess, tok, dev


@dataclass
class Adherence:
    score: float          # cosine similarity, roughly -1 to 1, in practice 0.1 to 0.4
    normalised: float     # rescaled to 0..1 against the usual working range


def _norm(sim: float, lo: float = 0.15, hi: float = 0.35) -> float:
    return float(min(1.0, max(0.0, (sim - lo) / (hi - lo))))


@torch.no_grad()
def score_many(images: list[np.ndarray], prompts: list[str]) -> list[Adherence]:
    """Pairwise: images[i] against prompts[i]."""
    if len(images) != len(prompts):
        raise ValueError("images and prompts must line up")
    net, preprocess, tok, dev = _load()

    px = torch.stack([preprocess(Image.fromarray(a)) for a in images]).to(dev)
    tx = tok(prompts).to(dev)

    im = net.encode_image(px)
    te = net.encode_text(tx)
    im = im / im.norm(dim=-1, keepdim=True)
    te = te / te.norm(dim=-1, keepdim=True)
    sims = (im * te).sum(dim=-1).float().cpu().numpy()
    return [Adherence(float(s), _norm(float(s))) for s in sims]


def score(image: np.ndarray, prompt: str) -> Adherence:
    return score_many([image], [prompt])[0]


@torch.no_grad()
def matrix(images: list[np.ndarray], prompts: list[str]) -> np.ndarray:
    """Every image against every prompt. Used to check the signal is real:
    the diagonal should beat the off-diagonal, or the score means nothing."""
    net, preprocess, tok, dev = _load()
    px = torch.stack([preprocess(Image.fromarray(a)) for a in images]).to(dev)
    tx = tok(prompts).to(dev)
    im = net.encode_image(px)
    te = net.encode_text(tx)
    im = im / im.norm(dim=-1, keepdim=True)
    te = te / te.norm(dim=-1, keepdim=True)
    return (im @ te.T).float().cpu().numpy()
