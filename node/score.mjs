// Scores a plan against the same checks the product runs, and returns the
// per-group breakdown rather than one number. Combining the groups into a
// single reward is the trainer's job, not this file's: keeping them separate is
// what lets us notice when two of them are measuring the same thing.
//
//   node node/score.mjs                 # worker, one job per stdin line
//   node node/score.mjs plan.json       # one shot, pretty printed
//
// job:  {"id":1,"plan":{...},"expect":["esp32-devkit","hc-sr04"]}
// out:  {"id":1,"ok":true,"terms":{...},"counts":{...},"issues":[...]}

import { createInterface } from 'node:readline'
import { readFileSync } from 'node:fs'
import { pathToFileURL } from 'node:url'
import { checkStructure, checkAssembly, checkElectrical, byId } from '@solder/core'

// errors past this many stop making things worse. linear decay in between so
// four errors is twice as bad as two, which exp() would not give us.
const CAP = Number(process.env.BRINGUP_ERROR_CAP ?? 3)
const WARN_WEIGHT = 0.25

function score(issues) {
  const errors = issues.filter((i) => i.level === 'error')
  const warns = issues.filter((i) => i.level === 'warn')
  const cost = errors.length + WARN_WEIGHT * warns.length
  return {
    value: Math.max(0, 1 - cost / CAP),
    errors: errors.length,
    warns: warns.length,
  }
}

// does the plan contain the parts the prompt implied. the checkers only care
// that a plan is legal; a two-part plan with one net is legal and useless.
function coverage(plan, expect) {
  if (!expect || !expect.length) return { value: null, hit: 0, want: 0, miss: [] }
  const have = new Set(plan.parts?.map((p) => p.part) ?? [])
  const miss = expect.filter((id) => !have.has(id))
  return {
    value: (expect.length - miss.length) / expect.length,
    hit: expect.length - miss.length,
    want: expect.length,
    miss,
  }
}

function wellFormed(plan) {
  if (!plan || typeof plan !== 'object') return 'plan is not an object'
  if (!Array.isArray(plan.parts) || !plan.parts.length) return 'plan has no parts'
  if (!Array.isArray(plan.nets) || !plan.nets.length) return 'plan has no nets'
  if (typeof plan.layout !== 'string') return 'plan has no layout'
  const unknown = plan.parts.filter((p) => !p || !byId[p.part])
  if (unknown.length === plan.parts.length) return 'no part resolves against the catalog'
  return null
}

export function scorePlan(plan, expect) {
  const bad = wellFormed(plan)
  if (bad) {
    return {
      ok: false,
      gate: 0,
      terms: { clean: 0, structure: 0, assembly: 0, electrical: 0, coverage: 0 },
      counts: { structure: [0, 0], assembly: [0, 0], electrical: [0, 0] },
      issues: [{ level: 'error', group: 'gate', msg: bad }],
      cover: { value: 0, hit: 0, want: expect?.length ?? 0, miss: expect ?? [] },
    }
  }

  const groups = {}
  const issues = []
  for (const [name, fn] of [
    ['structure', checkStructure],
    ['assembly', checkAssembly],
    ['electrical', checkElectrical],
  ]) {
    let found
    try {
      found = fn(plan) ?? []
    } catch (e) {
      found = [{ level: 'error', msg: `${name} check threw: ${e.message}` }]
    }
    groups[name] = score(found)
    for (const i of found) issues.push({ ...i, group: name })
  }

  const cover = coverage(plan, expect)
  return {
    ok: issues.every((i) => i.level !== 'error'),
    gate: 1,
    terms: {
      // what the product actually cares about. the graded terms below only
      // exist to give a gradient toward it.
      clean: issues.some((i) => i.level === 'error') ? 0 : 1,
      structure: groups.structure.value,
      assembly: groups.assembly.value,
      electrical: groups.electrical.value,
      coverage: cover.value,
    },
    counts: {
      structure: [groups.structure.errors, groups.structure.warns],
      assembly: [groups.assembly.errors, groups.assembly.warns],
      electrical: [groups.electrical.errors, groups.electrical.warns],
    },
    issues,
    cover,
  }
}

// only act as a cli when run directly; importers get scorePlan and nothing else
const direct = process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href
const arg = direct ? process.argv[2] : null
if (direct && arg) {
  const plan = JSON.parse(readFileSync(arg, 'utf8'))
  console.log(JSON.stringify(scorePlan(plan, null), null, 2))
} else if (direct) {
  const rl = createInterface({ input: process.stdin })
  rl.on('line', (raw) => {
    if (!raw.trim()) return
    let job
    try {
      job = JSON.parse(raw)
    } catch {
      process.stdout.write(JSON.stringify({ ok: false, error: 'bad json' }) + '\n')
      return
    }
    const out = scorePlan(job.plan, job.expect)
    process.stdout.write(JSON.stringify({ id: job.id, ...out }) + '\n')
  })
}
