"""The side-by-side sheet: prompts down, models across.

The svg is inlined rather than shown as a png, so it stays crisp at any zoom and
you can open devtools on a cell to read the markup that produced it. A raster
would hide exactly the thing being compared.

    python -m bringup.sheet --run 2026-09-10
"""

from __future__ import annotations

import argparse
import html
import json
import re
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RUNS = ROOT / "runs"
PROMPTS = ROOT / "data/illus/prompts.json"

# the sheet sets the cell size, so a fixed width/height on the svg would fight it
_SIZE_ATTR = re.compile(r'\s(?:width|height)\s*=\s*"[^"]*"')

CSS = """
:root { --line:#e4e4e7; --dim:#71717a; --bg:#fafafa; --card:#fff; --ink:#18181b; --bad:#dc2626; }
* { box-sizing:border-box }
body { margin:0; background:var(--bg); color:var(--ink);
  font:13px/1.5 ui-sans-serif,-apple-system,system-ui,sans-serif }
header { padding:24px 28px 8px; }
h1 { margin:0; font-size:18px; font-weight:600; letter-spacing:-.01em }
.meta { color:var(--dim); font-size:12px; margin-top:4px }
table { border-collapse:separate; border-spacing:0; width:100%; }
th,td { border-bottom:1px solid var(--line); vertical-align:top; padding:14px }
thead th { position:sticky; top:0; background:var(--bg); z-index:2; text-align:left;
  font-weight:600; font-size:12px; border-bottom:1px solid var(--line) }
.prompt { width:280px; min-width:280px }
.pid { font:11px ui-monospace,Menlo,monospace; color:var(--dim) }
.fam { display:inline-block; font:10px ui-monospace,Menlo,monospace; color:var(--dim);
  border:1px solid var(--line); border-radius:99px; padding:1px 7px; margin-left:6px }
.ptext { margin-top:6px; color:#3f3f46 }
.art { background:var(--card); border:1px solid var(--line); border-radius:10px;
  height:210px; display:grid; place-items:center; overflow:hidden; padding:10px }
.art svg { max-width:100%; max-height:100%; height:auto; width:auto; display:block }
.foot { margin-top:7px; font:11px ui-monospace,Menlo,monospace; color:var(--dim);
  display:flex; gap:10px; flex-wrap:wrap }
.fail { color:var(--bad) }
.empty { color:var(--dim); font-style:italic }
"""


def inline(svg: str) -> str:
    return _SIZE_ATTR.sub("", svg, count=2)


GRID_CSS = """
.grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(250px,1fr)); gap:16px; padding:0 28px 40px }
.card { background:var(--card); border:1px solid var(--line); border-radius:12px; overflow:hidden }
.card .art { height:200px; border:0; border-bottom:1px solid var(--line); border-radius:0 }
.card .cap { padding:10px 12px }
.card .cap p { margin:0 0 6px; color:#3f3f46; font-size:12px; line-height:1.45 }
"""


def grid(run_dir, provs, prompts, run):
    """One card per drawing. A 142-row table is not something anyone scans."""
    prov = provs[0]
    by_id = {p["id"]: p for p in prompts}
    cards = []
    for f in sorted((run_dir / prov).glob("*.svg")):
        pid = f.stem
        p = by_id.get(pid)
        if not p:
            continue
        meta_f = f.with_suffix(".json")
        m = json.loads(meta_f.read_text()) if meta_f.exists() else {}
        info = m.get("info") or {}
        bits = [f'{m.get("ms",0)//1000}s']
        if "bytes" in info:
            bits.append(f'{info["bytes"]}b')
        if "shapes" in info:
            bits.append(f'{info["shapes"]} shapes')
        g = m.get("gates") or {}
        if g:
            bits.append("gates ok" if g.get("passed")
                        else f'<span class="fail">{",".join(g.get("failed", []))}</span>')
        cards.append(
            f'<div class="card"><div class="art">{inline(f.read_text())}</div>'
            f'<div class="cap"><p>{html.escape(p["prompt"])}</p>'
            f'<div class="foot"><span class="pid">{pid}</span> {" ".join(bits)}</div></div></div>'
        )
    doc = (
        f'<!doctype html><meta charset="utf-8"><title>{prov} {run}</title>'
        f"<style>{CSS}{GRID_CSS}</style>"
        f'<header><h1>{prov} &middot; {len(cards)} drawings</h1>'
        f'<div class="meta">run {run} &middot; svg inlined, not rasterised</div></header>'
        f'<div class="grid">{"".join(cards)}</div>'
    )
    out = run_dir / "gallery.html"
    out.write_text(doc)
    print(f"wrote {out}  ({len(cards)} drawings)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default=date.today().isoformat())
    ap.add_argument("--prompts", default=str(PROMPTS),
                    help="prompt file; defaults to the held-out eval set")
    ap.add_argument("--grid", action="store_true",
                    help="one card per drawing instead of a prompt-by-model table. "
                         "for browsing a single provider's run, where the table would be "
                         "one very long column")
    args = ap.parse_args()

    run_dir = RUNS / args.run
    if not run_dir.exists():
        print(f"no run at {run_dir}")
        return 1

    provs = sorted(d.name for d in run_dir.iterdir() if d.is_dir())
    prompts = json.loads(Path(args.prompts).read_text())

    if args.grid:
        return grid(run_dir, provs, prompts, args.run)

    rows = []
    for p in prompts:
        cells = []
        for prov in provs:
            meta_f = run_dir / prov / f"{p['id']}.json"
            svg_f = run_dir / prov / f"{p['id']}.svg"
            if not meta_f.exists():
                cells.append('<td><div class="art"><span class="empty">not run</span></div></td>')
                continue
            m = json.loads(meta_f.read_text())
            if svg_f.exists():
                art = f'<div class="art">{inline(svg_f.read_text())}</div>'
            else:
                art = f'<div class="art"><span class="empty">{html.escape(str(m.get("error"))[:80])}</span></div>'
            g = m.get("gates") or {}
            bits = [f'{m.get("ms",0)}ms']
            info = m.get("info") or {}
            if "bytes" in info:
                bits.append(f'{info["bytes"]}b')
            if "shapes" in info:
                bits.append(f'{info["shapes"]} shapes')
            if g:
                bits.append("gates ok" if g.get("passed")
                            else f'<span class="fail">{",".join(g.get("failed", []))}</span>')
            cells.append(f'<td>{art}<div class="foot">{" ".join(bits)}</div></td>')

        rows.append(
            f'<tr><td class="prompt"><span class="pid">{p["id"]}</span>'
            f'<span class="fam">{p["family"]}</span>'
            f'<div class="ptext">{html.escape(p["prompt"])}</div></td>'
            + "".join(cells) + "</tr>"
        )

    models = {}
    for prov in provs:
        for f in (run_dir / prov).glob("*.json"):
            models[prov] = json.loads(f.read_text()).get("model", prov)
            break

    head = "".join(f'<th>{prov}<div class="pid">{models.get(prov,"")}</div></th>' for prov in provs)
    doc = (
        f'<!doctype html><meta charset="utf-8"><title>arena {args.run}</title>'
        f"<style>{CSS}</style>"
        f'<header><h1>same prompt, every model</h1>'
        f'<div class="meta">run {args.run} &middot; {len(prompts)} prompts &middot; '
        f'{len(provs)} models &middot; svg inlined, not rasterised</div></header>'
        f'<table><thead><tr><th class="prompt">prompt</th>{head}</tr></thead>'
        f"<tbody>{''.join(rows)}</tbody></table>"
    )
    out = run_dir / "index.html"
    out.write_text(doc)
    print(f"wrote {out}  ({len(prompts)} rows x {len(provs)} models)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
