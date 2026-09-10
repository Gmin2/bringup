# bringup

Training a small open model to write Solder build plans that pass on the first
attempt.

Solder turns a prompt into a hardware build: which catalog parts, how they wire
together, where each one sits in millimetres. A frontier model does that today
and gets it right first try about 75% of the time; the rest cost a repair round,
which is most of the 53 second wait. This repo is the attempt to close that gap
with a model we run ourselves.

The reason it is worth trying here and not somewhere else: the reward already
exists. `@solder/core` ships `checkStructure`, `checkAssembly` and
`checkElectrical`, which between them catch missing ground nets, footprints that
overlap by 4mm, pins that are not on the part, voltages a pin cannot tolerate,
and a current budget the supply cannot meet. A plan is right or wrong the same
way a test passes or fails, so no judge and no hand-rated pool is needed.

## Layout

    node/score.mjs      the checks, wrapped as a JSONL worker
    node/normalize.mjs  the same normalisation the composer applies before checking
    node/recorder.mjs   a provider wrapper that keeps every attempt
    node/generate.mjs   runs prompts through the real composer
    node/prompts.mjs    builds a prompt set out of catalog combinations
    bringup/scorer.py   python client for the scorer
    bringup/sft.py      runs -> supervised examples
    bench/degrade.py    named, deliberate ways to break a plan
    bench/reward_sanity.py    does the reward rank good plans above broken ones
    bench/repair_capture.mjs  does a repair round actually get recorded
    data/               prompts and generated plans, all gitignored
    runs/               one directory per training run

`@solder/core` is linked, not vendored, so the reward can never drift from what
the product checks. It resolves through `node_modules/@solder/core` to
`../../portfolio/ui/tools/svgs/vector-hardware/packages/core`.

## Running

    pnpm install
    uv venv --python 3.12 && uv pip install numpy
    .venv/bin/python bench/reward_sanity.py

## The reward

Five terms, kept separate and combined by the trainer, never collapsed inside
the scorer:

    clean        1 if the plan has zero errors. what we actually want.
    structure    graded, refs and nets on their own
    assembly     graded, geometry against real part dimensions
    electrical   graded, against the catalog
    coverage     fraction of the parts the prompt implied that made it in

The graded terms exist to give a gradient toward `clean`, and `coverage` exists
because the checks reward legality rather than usefulness: a two part plan with
one net is legal and worthless.

## What the sanity check says today

29 of the 40 saved eval plans score perfect, and the other 11 are informative:

- four have real errors, all bench overlaps (`bracket-blinds`,
  `bracket-stepper`, `chassis-drone`, `free-keypad-lock`). They are not clean and
  must not go into the SFT set.
- the rest carry warnings only.

Every named degradation scores lower than its clean parent, and stacking more of
them keeps lowering it. The four graded terms correlate no higher than 0.41 with
each other, so none of them is a second copy of another.

Known gap: the `overlap` degradation only makes 21 of 26 plans worse, because on
some plans the two parts it moves together were already overlapping, so no new
error appears. That is the test being blunt, not the reward being wrong.

## Rendering

Scoring a drawing means rasterising it, and that has to give the same pixels on
a laptop and on the training box. resvg is reproducible across platforms except
for one thing: it resolves font family names against whatever is installed. So
`fonts/` ships DejaVu Sans and DejaVu Sans Mono, resvg is told to ignore system
fonts, and every font stack in the SVG is rewritten down to `monospace` or
`sans-serif`, which are the two names it can actually map.

That rewrite is part of the canonical render path, so it has to be applied to
model output and to reference targets alike. Everything goes through
`rasterize`. DejaVu Sans Mono is what Menlo derives from, so pinning it barely
moves the text compared to what the harness playground shows.

    .venv/bin/python bench/render_determinism.py

Three questions, because a font pin that silently falls back looks identical to
one that works until you run it somewhere else: does every file render, is a
repeated render byte-identical, and does removing the font files change the
output on text-bearing files. Over the 112 solder SVGs: 112 render, 112 stable,
and all 37 text-bearing files change when the fonts are removed.

Speed, measured: 11.6ms for a 5KB part at 512px, 21.4ms for a 61KB assembly. A
browser render is ~300ms cold. RL renders every rollout, so that ratio decides
how much training is affordable.

## Data

`compose()` only returns the plan it settled on. The attempts it discarded are
the more interesting half: a broken plan, the errors it drew, and the fix. It
takes a provider though, so `node/recorder.mjs` wraps one and keeps every call
without anything in the product having to change.

    node node/prompts.mjs --n=2000 --out=data/prompts.json
    node --env-file=<vh>/.env node/generate.mjs all --prompts=data/prompts.json --jobs=8
    .venv/bin/python bringup/sft.py

Prompts are built by combining real catalog parts rather than written by a
model, so the expected part list is exact. The weakness is phrasing: generated
prompts read more uniform than a person typing into a box. The 40 hand-written
eval prompts are held out and never generated over, partly for that reason.

Two things to know about the numbers. A prompt costs roughly 13.4k input tokens,
nearly all of it cache hits after the first call, and 1.4k to 4.7k output.
And scoring the raw model output is wrong: the composer runs `clean()` and a pin
tidy before it checks anything, so `node/normalize.mjs` does the same, importing
`clean()` from the live source rather than copying it.

## Gates

With text conditioning there is no target image, so `rasterize` has nothing to
compare against and the pixel metrics lose their referent. That makes the free
checks carry more weight than they otherwise would: they are the only part of
the reward that cannot be argued with.

`bringup/gates.py` is those checks. Each one exists because of a specific cheat:

    no_raster           embedding a png and calling it a drawing
    no_foreign_object   html that only renders in a browser, blank in resvg
    viewbox_sane        shrinking the viewBox until the canvas is near-empty,
                        a documented RLRF reward hack
    ink_ok              a blank canvas, or one flooded with a single fill
    varied              a solid rectangle passes every other check
    length_ok           runaway generation, and stubs too small to be a drawing
    shapes_ok           same, on geometry rather than bytes
    parses / is_svg     output that is not svg

    .venv/bin/python bench/gate_sanity.py

The check asserts each cheat trips its *own* gate, not merely that the result
fails overall, so a cheat cannot be caught by accident while the gate meant to
catch it never fires. It also runs the 112 real drawings through, because a gate
that rejects real work is as broken as one that lets cheats through. That second
half earned its keep immediately: the first length cap was a guess and threw out
three genuine assemblies, so the bounds are now taken from the corpus, which
runs 1.6KB to 75KB with a 7.5KB median and 5 to 407 shapes.

## The floor

Before choosing a base model or a training recipe, measure what a small open
model does cold on the same 34 prompts. `bringup/serve.py` runs one locally
through mlx, which serves an openai-compatible endpoint, so the arena reaches it
with no new code.

    python -m bringup.serve --model mlx-community/Qwen3-4B-Instruct-2507-4bit
    LOCAL_MODEL=... LOCAL_NAME=qwen3-4b python -m bringup.arena --providers qwen3-4b

Local rather than an aggregator on purpose: the model measured is byte for byte
the model that would be trained, with no provider quantisation or serving
differences in between.

    family          gpt  quiver  qwen4b      gptB    qvB    4bB     gpt s  4b s
    hardware        8/8    8/8     7/8      13554  13262   2743      129    18
    product-ui      8/8    8/8     6/8       5266  10216   2001       42    12
    scene           8/8    7/8     8/8       4993   3801   2546       48    16
    icon            6/6    6/6     6/6         380    922    624       11     5
    logo            4/4    4/4     4/4         337   1210    449       13     3

Qwen3-4B returns valid svg on all 34 and passes gates on 31, so rollouts will
not be degenerate from step one. The gap is density and adherence, not
validity: hardware drawings are a fifth the size of gpt's, and clip retrieval is
16/31 top-1 against gpt's 27/34. That gap is what a rendering reward is for.

The three gate failures are xml hygiene, not drawing: a raw `&` in a text label
and two duplicate attributes. Those are the easiest thing for rl to fix, since
the gate gives an unambiguous binary signal.
