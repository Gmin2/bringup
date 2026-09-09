"""Run every prompt through every configured model and keep everything.

Resumable on purpose. Quiver generations cost credits and OpenAI calls cost
money, so a rate limit or a crash halfway through must never mean paying twice:
if the svg for a (provider, prompt) already exists on disk, it is skipped.

Nothing is judged here beyond the gates. This produces the artifacts; scoring
taste comes later and reads from the same directory.

    python -m bringup.arena                        # every configured provider
    python -m bringup.arena --providers openai     # just one column
    python -m bringup.arena --run 2026-09-10 --jobs 4
"""

from __future__ import annotations

import argparse
import json
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

from bringup.gates import check
from bringup.providers import available, load_env
from bringup.render import RenderError, rasterize, save_png

ROOT = Path(__file__).resolve().parent.parent
PROMPTS = ROOT / "data/illus/prompts.json"
RUNS = ROOT / "runs"


def one(provider, prompt: dict, out: Path, width: int) -> dict:
    svg_path = out / f"{prompt['id']}.svg"
    meta_path = out / f"{prompt['id']}.json"

    if meta_path.exists():
        row = json.loads(meta_path.read_text())
        row["skipped"] = True
        return row

    g = provider.generate(prompt["prompt"], prompt["id"])
    row = {
        "id": prompt["id"],
        "family": prompt["family"],
        "provider": provider.name,
        "model": provider.model,
        "ms": g.ms,
        "usage": g.usage,
        "error": g.error,
        "ok": g.ok,
    }

    if g.ok:
        svg_path.write_text(g.svg)
        r = check(g.svg)
        row["gates"] = {"passed": r.passed, "failed": [k for k, v in r.checks.items() if not v]}
        row["info"] = r.info
        row["reasons"] = r.reasons
        try:
            save_png(rasterize(g.svg, width=width), out / f"{prompt['id']}.png")
        except RenderError as e:
            row["render_error"] = str(e)[:200]
    else:
        # keep what the model actually said, so a non-svg reply is inspectable
        (out / f"{prompt['id']}.raw.txt").write_text(g.raw or "")

    meta_path.write_text(json.dumps(row, indent=1))
    return row


def rescore(run_dir: Path, width: int) -> int:
    """Gates change as we learn what they should have been. Re-running them over
    stored svgs costs nothing, so a calibration fix never means paying for the
    generations again."""
    changed = 0
    for meta_path in sorted(run_dir.glob("*/*.json")):
        if meta_path.name == "rows.json":
            continue
        svg_path = meta_path.with_suffix(".svg")
        if not svg_path.exists():
            continue
        row = json.loads(meta_path.read_text())
        before = (row.get("gates") or {}).get("passed")
        r = check(svg_path.read_text())
        row["gates"] = {"passed": r.passed, "failed": [k for k, v in r.checks.items() if not v]}
        row["info"] = r.info
        row["reasons"] = r.reasons
        meta_path.write_text(json.dumps(row, indent=1))
        if before is not r.passed:
            changed += 1
            print(f"  {row['provider']:8} {row['id']:14} {before} -> {r.passed}  {r.info.get('ink')}")
    print(f"rescored {run_dir}, {changed} verdicts changed")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--providers", default="", help="comma separated; default is every configured one")
    ap.add_argument("--run", default=date.today().isoformat())
    ap.add_argument("--jobs", type=int, default=3)
    ap.add_argument("--width", type=int, default=512)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--family", default="", help="only prompts in this family")
    ap.add_argument("--rescore", action="store_true",
                    help="re-run the gates over svgs already on disk, no api calls")
    args = ap.parse_args()

    load_env()
    provs = available()
    if args.providers:
        want = {p.strip() for p in args.providers.split(",")}
        provs = [p for p in provs if p.name in want]
    if not provs:
        print("no providers configured. check .env")
        return 1

    prompts = json.loads(PROMPTS.read_text())
    if args.family:
        prompts = [p for p in prompts if p["family"] == args.family]
    if args.limit:
        prompts = prompts[: args.limit]

    run_dir = RUNS / args.run
    print(f"{len(prompts)} prompts x {len(provs)} providers -> {run_dir}")
    for p in provs:
        print(f"  {p.name}/{p.model}")

    if args.rescore:
        return rescore(run_dir, args.width)

    started = time.perf_counter()
    rows = []
    for prov in provs:
        out = run_dir / prov.name
        out.mkdir(parents=True, exist_ok=True)
        done = 0
        with ThreadPoolExecutor(max_workers=args.jobs) as ex:
            for row in ex.map(lambda pr: one(prov, pr, out, args.width), prompts):
                done += 1
                rows.append(row)
                tag = "skip" if row.get("skipped") else ("ok  " if row["ok"] else "FAIL")
                gate = ""
                if row["ok"] and "gates" in row:
                    gate = "gates ok" if row["gates"]["passed"] else "gates " + ",".join(row["gates"]["failed"])
                print(f"  [{done:3}/{len(prompts)}] {tag} {prov.name:7} {row['id']:14} "
                      f"{row['ms']:6}ms  {gate}  {row.get('error') or ''}")

    (run_dir / "rows.json").write_text(json.dumps(rows, indent=1))

    print()
    for prov in provs:
        mine = [r for r in rows if r["provider"] == prov.name]
        got = [r for r in mine if r["ok"]]
        passed = [r for r in got if r.get("gates", {}).get("passed")]
        fresh = [r for r in mine if not r.get("skipped")]
        print(f"{prov.name:8} returned svg {len(got)}/{len(mine)}  gates passed {len(passed)}/{len(mine)}  "
              f"new calls {len(fresh)}")
    print(f"wall {time.perf_counter() - started:.0f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
