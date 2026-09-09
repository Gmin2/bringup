// Whatever the model emits has to go through exactly the same normalisation the
// composer applies before the checks run, or the reward disagrees with the
// product about whether a plan is clean.
//
// Both halves come from the live source rather than being copied: clean() is
// imported, and the pin tidy mirrors tidyPins() in compose/composer.ts. If that
// regex ever changes there, this is the line to change.

import { clean } from '../node_modules/@solder/core/src/compose/schema.ts'

export function normalize(raw) {
  const plan = clean(typeof raw === 'string' ? JSON.parse(raw) : raw)
  for (const n of plan?.nets ?? []) {
    if (Array.isArray(n.pins)) n.pins = n.pins.map((p) => String(p).replace(/\s*\([^)]*\)\s*$/, '').trim())
  }
  return plan
}

export function tryNormalize(raw) {
  try {
    return { plan: normalize(raw), error: null }
  } catch (e) {
    return { plan: null, error: e.message }
  }
}
