"""Deliberate damage, one named mistake per function.

The point is not to simulate a model. It is to check the reward moves the right
way when something specific and known is wrong with a plan, before we trust it
to rank things nobody has looked at.
"""

from __future__ import annotations

import copy
import random


def _copy(plan):
    return copy.deepcopy(plan)


def drop_ground(plan, rng):
    p = _copy(plan)
    p["nets"] = [n for n in p["nets"] if n.get("kind") != "ground"]
    return p


def drop_power(plan, rng):
    p = _copy(plan)
    p["nets"] = [n for n in p["nets"] if n.get("kind") != "power"]
    return p


def truncate_net(plan, rng):
    p = _copy(plan)
    big = [n for n in p["nets"] if len(n.get("pins", [])) > 2]
    if not big:
        return None
    rng.choice(big)["pins"] = [rng.choice(big)["pins"][0]]
    return p


def orphan_part(plan, rng):
    p = _copy(plan)
    src = rng.choice(p["parts"])
    p["parts"].append({**src, "ref": src["ref"] + "_spare"})
    return p


def unknown_part_id(plan, rng):
    p = _copy(plan)
    rng.choice(p["parts"])["part"] = "definitely-not-a-part"
    return p


def bad_pin(plan, rng):
    p = _copy(plan)
    nets = [n for n in p["nets"] if n.get("pins")]
    if not nets:
        return None
    net = rng.choice(nets)
    ref = net["pins"][0].split(".")[0]
    net["pins"][0] = f"{ref}.ZZZ99"
    return p


def unplace(plan, rng):
    p = _copy(plan)
    if not p.get("assembly"):
        return None
    p["assembly"].pop(rng.randrange(len(p["assembly"])))
    return p


def overlap(plan, rng):
    p = _copy(plan)
    bench = [a for a in (p.get("assembly") or []) if not a.get("on")]
    if len(bench) < 2:
        return None
    a, b = rng.sample(bench, 2)
    b["at"] = list(a["at"])
    return p


def off_face(plan, rng):
    p = _copy(plan)
    mounted = [a for a in (p.get("assembly") or []) if a.get("on")]
    if not mounted:
        return None
    rng.choice(mounted)["at"] = [9999, 9999]
    return p


def self_mount(plan, rng):
    p = _copy(plan)
    if not p.get("assembly"):
        return None
    e = rng.choice(p["assembly"])
    e["on"] = e["ref"]
    return p


def drop_half_parts(plan, rng):
    p = _copy(plan)
    keep = max(1, len(p["parts"]) // 2)
    p["parts"] = p["parts"][:keep]
    return p


def empty_plan(plan, rng):
    p = _copy(plan)
    p["parts"] = []
    p["nets"] = []
    return p


ALL = {
    "drop_ground": drop_ground,
    "drop_power": drop_power,
    "truncate_net": truncate_net,
    "orphan_part": orphan_part,
    "unknown_part_id": unknown_part_id,
    "bad_pin": bad_pin,
    "unplace": unplace,
    "overlap": overlap,
    "off_face": off_face,
    "self_mount": self_mount,
    "drop_half_parts": drop_half_parts,
    "empty_plan": empty_plan,
}

# things a model plausibly gets wrong, for the more-damage-scores-lower ladder.
LADDER = [k for k in ALL if k not in ("empty_plan", "drop_half_parts")]


def stack(plan, kinds, seed=0):
    rng = random.Random(seed)
    p = plan
    applied = []
    for k in kinds:
        nxt = ALL[k](p, rng)
        if nxt is None:
            continue
        p, _ = nxt, applied.append(k)
    return p, applied
