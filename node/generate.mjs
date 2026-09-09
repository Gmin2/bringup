// Runs prompts through the real composer and keeps everything it produced,
// including the attempts compose() discards.
//
//   node --env-file=<vh>/.env node/generate.mjs bb-dice plate-solar
//   node --env-file=<vh>/.env node/generate.mjs all --limit=5 --jobs=8
//   node --env-file=<vh>/.env node/generate.mjs all --prompts=data/prompts.json --jobs=12
//
// One file per prompt in data/plans/, holding the settled plan, every attempt
// with the ask that produced it, and the score of each attempt.

import { mkdirSync, writeFileSync, readFileSync, existsSync } from 'node:fs'
import { createHash } from 'node:crypto'
import { join, dirname } from 'node:path'
import { compose } from '@solder/core'
import { scorePlan } from './score.mjs'
import { recordingProvider } from './recorder.mjs'
import { tryNormalize } from './normalize.mjs'

const VH = join(process.env.HOME, 'coding/portfolio/ui/tools/svgs/vector-hardware')
const OUT = process.env.BRINGUP_OUT ?? 'data/plans'

const args = process.argv.slice(2)
// bare --redo has no '=', so give it true rather than undefined
const flags = Object.fromEntries(
  args
    .filter((a) => a.startsWith('--'))
    .map((a) => {
      const [k, v] = a.replace(/^--/, '').split('=')
      return [k, v ?? true]
    }),
)
const wanted = args.filter((a) => !a.startsWith('--'))

const promptsFile = flags.prompts ?? join(VH, 'packages/core/evals/prompts.json')
const all = JSON.parse(readFileSync(promptsFile, 'utf8'))
let cases = wanted.length && wanted[0] !== 'all' ? all.filter((p) => wanted.includes(p.id)) : all
if (flags.limit) cases = cases.slice(0, Number(flags.limit))
if (!flags.redo) cases = cases.filter((c) => !existsSync(join(OUT, `${c.id}.json`)))

mkdirSync(OUT, { recursive: true })
console.log(`${cases.length} prompts -> ${OUT}`)

async function run(c) {
  const provider = recordingProvider()
  const t0 = Date.now()
  let r
  try {
    r = await compose(c.prompt, { maxAttempts: Number(flags.attempts ?? 3), provider })
  } catch (e) {
    return { id: c.id, error: e.message, seconds: (Date.now() - t0) / 1000 }
  }
  const seconds = +((Date.now() - t0) / 1000).toFixed(1)

  const attempts = provider.calls.map((call) => {
    const { plan, error } = tryNormalize(call.text || '')
    const s = plan ? scorePlan(plan, c.expect) : null
    return {
      ask: call.ask,
      text: call.text,
      usage: call.usage,
      parseError: error,
      ok: s?.ok ?? false,
      terms: s?.terms ?? null,
      errors: s ? s.issues.filter((i) => i.level === 'error').map((i) => i.msg) : [],
    }
  })

  // one copy of the system prompt for the whole run; if it ever differs between
  // runs the hash on the plan file says so
  const sysHash = createHash('sha256').update(provider.system ?? '').digest('hex').slice(0, 12)
  const sysFile = join(dirname(OUT), `system-${sysHash}.txt`)
  if (provider.system && !existsSync(sysFile)) writeFileSync(sysFile, provider.system)

  const final = r.plan ? scorePlan(r.plan, c.expect) : null
  const row = {
    id: c.id,
    prompt: c,
    seconds,
    attempts: r.attempts,
    clean: final?.ok ?? false,
    terms: final?.terms ?? null,
    tokensIn: provider.calls.reduce((a, c) => a + (c.usage?.input ?? 0), 0),
    tokensOut: provider.calls.reduce((a, c) => a + (c.usage?.output ?? 0), 0),
  }
  writeFileSync(
    join(OUT, `${c.id}.json`),
    JSON.stringify({ ...row, system: sysHash, plan: r.plan, calls: attempts }, null, 2),
  )
  return row
}

const JOBS = Number(flags.jobs ?? 1)
const rows = []
const started = Date.now()
let next = 0
let finished = 0

function report(row) {
  finished++
  const first = row.error ? '-' : row.attempts === 1 && row.clean
  const head = `[${String(finished).padStart(4)}/${cases.length}] ${row.id.padEnd(22)}`
  console.log(
    head +
      (row.error
        ? `ERROR ${row.error}`
        : `${String(row.seconds).padStart(5)}s  att ${row.attempts}  clean ${row.clean}  first ${first}  ${row.tokensIn}/${row.tokensOut}`),
  )
}

async function worker() {
  while (next < cases.length) {
    const c = cases[next++]
    const row = await run(c)
    rows.push(row)
    report(row)
  }
}

await Promise.all(Array.from({ length: Math.min(JOBS, cases.length) }, worker))

const done = rows.filter((r) => !r.error)
const pct = (n) => `${((100 * n) / Math.max(1, done.length)).toFixed(0)}%`
console.log(
  `\n${done.length} ran  clean ${pct(done.filter((r) => r.clean).length)}  ` +
    `first attempt clean ${pct(done.filter((r) => r.clean && r.attempts === 1).length)}  ` +
    `tokens ${done.reduce((a, r) => a + r.tokensIn, 0)}/${done.reduce((a, r) => a + r.tokensOut, 0)}  ` +
    `wall ${((Date.now() - started) / 1000).toFixed(0)}s at ${Math.min(JOBS, cases.length)} jobs`,
)
