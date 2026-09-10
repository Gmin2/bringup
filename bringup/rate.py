"""Build the rating page: blind pairwise comparisons over a run.

Four answers, not three. Better-left and better-right are the ranking signal;
both-good and both-bad are the ones that decide what goes in the pool at all.
A plain "tie" would collapse those two, and they mean opposite things: both good
means both belong in the reference pool, both bad means no model can do this
prompt and ranking two failures would only teach a judge to prefer one kind of
failure.

Pairwise rather than a 0-10 score, because that is what surya's post-mortem
found: asked to score a drawing out of ten, a judge bunches everything near the
bottom and the reward has almost no dynamic range. Asked which of two is better,
it answers reliably, and the same is true of a person.

Blind and shuffled: the model names are not shown and left/right is randomised
per pair, so a preference for a familiar style cannot leak in.

    python -m bringup.rate --run 2026-09-10
    open runs/2026-09-10/rate.html

Ratings live in the browser as you go and export as json when you are done.
"""

from __future__ import annotations

import argparse
import html
import json
import random
import re
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RUNS = ROOT / "runs"
PROMPTS = ROOT / "data/illus/prompts.json"

_SIZE_ATTR = re.compile(r'\s(?:width|height)\s*=\s*"[^"]*"')

CSS = """
:root { --line:#e4e4e7; --dim:#71717a; --bg:#fafafa; --card:#fff; --ink:#18181b;
        --pick:#2563eb; --ok:#16a34a }
* { box-sizing:border-box }
body { margin:0; background:var(--bg); color:var(--ink); font:14px/1.5 ui-sans-serif,-apple-system,system-ui,sans-serif }
.wrap { max-width:1180px; margin:0 auto; padding:20px 24px 80px }
header { display:flex; align-items:baseline; gap:14px; margin-bottom:4px }
h1 { font-size:17px; font-weight:600; margin:0; letter-spacing:-.01em }
.count { color:var(--dim); font:12px ui-monospace,Menlo,monospace }
.bar { height:3px; background:var(--line); border-radius:2px; margin:12px 0 20px; overflow:hidden }
.bar i { display:block; height:100%; background:var(--pick); width:0; transition:width .2s }
.prompt { background:var(--card); border:1px solid var(--line); border-radius:10px;
  padding:14px 16px; margin-bottom:16px }
.fam { font:10px ui-monospace,Menlo,monospace; color:var(--dim); border:1px solid var(--line);
  border-radius:99px; padding:1px 8px; margin-right:8px }
.pair { display:grid; grid-template-columns:1fr 1fr; gap:16px }
.side { background:var(--card); border:2px solid var(--line); border-radius:12px;
  padding:12px; cursor:pointer; transition:border-color .12s, transform .08s }
.side:hover { border-color:#a1a1aa }
.side:active { transform:scale(.995) }
.side.pick { border-color:var(--pick) }
.art { height:330px; display:grid; place-items:center; overflow:hidden }
.art svg { max-width:100%; max-height:100%; width:auto; height:auto; display:block }
.key { text-align:center; font:11px ui-monospace,Menlo,monospace; color:var(--dim); margin-top:8px }
.row { display:flex; gap:10px; justify-content:center; margin-top:18px }
button { font:13px ui-sans-serif,system-ui,sans-serif; padding:8px 18px; border-radius:8px;
  border:1px solid var(--line); background:var(--card); cursor:pointer; color:var(--ink) }
button:hover { border-color:#a1a1aa }
button.primary { background:var(--ink); color:#fff; border-color:var(--ink) }
.done { text-align:center; padding:60px 0 }
.done h2 { font-size:20px; margin:0 0 10px }
.hint { color:var(--dim); font-size:12px; text-align:center; margin-top:26px; line-height:1.9 }
kbd { font:11px ui-monospace,Menlo,monospace; border:1px solid var(--line); border-bottom-width:2px;
  border-radius:4px; padding:1px 6px; background:var(--card) }
"""

JS = """
const PAIRS = __PAIRS__;
const KEY = 'bringup-ratings-__RUN__';
let done = JSON.parse(localStorage.getItem(KEY) || '{}');
let i = PAIRS.findIndex(p => !(p.id in done));
if (i < 0) i = PAIRS.length;

const $ = s => document.querySelector(s);

function render() {
  if (i >= PAIRS.length) return finish();
  const p = PAIRS[i];
  $('#count').textContent = `${Object.keys(done).length} of ${PAIRS.length} rated`;
  $('#bar').style.width = (100 * Object.keys(done).length / PAIRS.length) + '%';
  $('#fam').textContent = p.family;
  $('#ptext').textContent = p.prompt;
  $('#left .art').innerHTML = p.a.svg;
  $('#right .art').innerHTML = p.b.svg;
  document.querySelectorAll('.side').forEach(e => e.classList.remove('pick'));
}

function choose(v) {
  if (i >= PAIRS.length) return;
  const p = PAIRS[i];
  // store the model names, not left/right, so the shuffle cannot corrupt it
  done[p.id] = { prompt_id: p.prompt_id, family: p.family,
                 winner: v === 'a' ? p.a.model : v === 'b' ? p.b.model : v,
                 a: p.a.model, b: p.b.model, at: Date.now() };
  localStorage.setItem(KEY, JSON.stringify(done));
  i++;
  render();
}

function finish() {
  $('#main').innerHTML = `<div class="done"><h2>all ${PAIRS.length} rated</h2>
    <p class="hint">save the file into the repo as <code>runs/__RUN__/ratings.json</code></p>
    <div class="row"><button class="primary" onclick="save()">download ratings.json</button>
    <button onclick="again()">rate again from the start</button></div></div>`;
  $('#count').textContent = `${Object.keys(done).length} of ${PAIRS.length} rated`;
  $('#bar').style.width = '100%';
}

function save() {
  const blob = new Blob([JSON.stringify(Object.values(done), null, 1)], {type:'application/json'});
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob); a.download = 'ratings.json'; a.click();
}

function again() { done = {}; localStorage.removeItem(KEY); i = 0; location.reload(); }

addEventListener('keydown', e => {
  if (e.key === 'ArrowLeft' || e.key === 'a') choose('a');
  else if (e.key === 'ArrowRight' || e.key === 'd') choose('b');
  else if (e.key === ' ' || e.key === 'g') { e.preventDefault(); choose('both_good'); }
  else if (e.key === 'x') choose('both_bad');
  else if (e.key === 's') choose('skip');
});

render();
"""


def inline(svg: str) -> str:
    return _SIZE_ATTR.sub("", svg, count=2)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default=date.today().isoformat())
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    run_dir = RUNS / args.run
    if not run_dir.exists():
        print(f"no run at {run_dir}")
        return 1

    provs = sorted(d.name for d in run_dir.iterdir() if d.is_dir())
    prompts = json.loads(PROMPTS.read_text())
    rng = random.Random(args.seed)

    pairs = []
    for p in prompts:
        got = [(prov, run_dir / prov / f"{p['id']}.svg") for prov in provs]
        got = [(prov, f) for prov, f in got if f.exists()]
        for x in range(len(got)):
            for y in range(x + 1, len(got)):
                two = [got[x], got[y]]
                rng.shuffle(two)  # kill position bias
                (ma, fa), (mb, fb) = two
                pairs.append({
                    "id": f"{p['id']}:{min(got[x][0], got[y][0])}|{max(got[x][0], got[y][0])}",
                    "prompt_id": p["id"],
                    "family": p["family"],
                    "prompt": p["prompt"],
                    "a": {"model": ma, "svg": inline(fa.read_text())},
                    "b": {"model": mb, "svg": inline(fb.read_text())},
                })
    rng.shuffle(pairs)  # so a partial session still spans every family

    doc = f"""<!doctype html><meta charset="utf-8"><title>rate {args.run}</title>
<style>{CSS}</style>
<div class="wrap">
<header><h1>which is the better drawing?</h1><span class="count" id="count"></span></header>
<div class="bar"><i id="bar"></i></div>
<div id="main">
  <div class="prompt"><span class="fam" id="fam"></span><span id="ptext"></span></div>
  <div class="pair">
    <div class="side" id="left" onclick="choose('a')"><div class="art"></div><div class="key">&larr; left</div></div>
    <div class="side" id="right" onclick="choose('b')"><div class="art"></div><div class="key">right &rarr;</div></div>
  </div>
  <div class="row">
    <button onclick="choose('both_good')">both good</button>
    <button onclick="choose('both_bad')">both bad</button>
    <button onclick="choose('skip')">skip</button>
    <button class="primary" onclick="save()">download so far</button>
  </div>
  <p class="hint"><kbd>&larr;</kbd> left is better &nbsp; <kbd>&rarr;</kbd> right is better &nbsp;
     <kbd>space</kbd> both good &nbsp; <kbd>x</kbd> both bad &nbsp; <kbd>s</kbd> skip<br>
     use both freely. whether a prompt is within reach at all matters more than a forced winner.<br>
     model names are hidden and sides are shuffled. progress saves as you go.</p>
</div></div>
<script>{JS.replace("__PAIRS__", json.dumps(pairs)).replace("__RUN__", args.run)}</script>"""

    out = run_dir / "rate.html"
    out.write_text(doc)
    n = len(prompts)
    print(f"wrote {out}")
    print(f"{len(pairs)} pairs from {len(provs)} models over {n} prompts")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
