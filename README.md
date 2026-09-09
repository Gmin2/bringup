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
    bringup/scorer.py   python client for it
    bench/degrade.py    named, deliberate ways to break a plan
    bench/reward_sanity.py   does the reward rank good plans above broken ones
    data/               prompts and generated plans
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
