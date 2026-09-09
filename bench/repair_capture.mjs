// Proves the recorder actually captures a repair round, without paying for a
// real one and hoping the model slips. A stub provider answers with a plan we
// broke on purpose first, then the good one, so the second ask must be the
// validator's complaint.
//
//   node bench/repair_capture.mjs

import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { compose } from '@solder/core'
import { recordingProvider } from '../node/recorder.mjs'
import { normalize } from '../node/normalize.mjs'
import { scorePlan } from '../node/score.mjs'

const VH = join(process.env.HOME, 'coding/portfolio/ui/tools/svgs/vector-hardware')
const good = JSON.parse(readFileSync(join(VH, 'packages/web/public/dev/eval/bb-dice.json'), 'utf8'))

const broken = structuredClone(good)
broken.nets = broken.nets.filter((n) => n.kind !== 'ground')

const replies = [JSON.stringify(broken), JSON.stringify(good)]
let n = 0
const stub = {
  name: 'stub',
  model: 'stub',
  async complete() {
    return { text: replies[Math.min(n++, replies.length - 1)], usage: { input: 0, output: 0 } }
  },
}

const provider = recordingProvider(stub)
const r = await compose('a dice on a breadboard', { maxAttempts: 3, provider })

const fail = (m) => {
  console.error('FAIL: ' + m)
  process.exit(1)
}

if (provider.calls.length !== 2) fail(`expected 2 calls, got ${provider.calls.length}`)
if (r.attempts !== 2) fail(`expected 2 attempts, got ${r.attempts}`)
if (!provider.calls[1].ask.includes('ERROR:')) fail('second ask does not carry the validator errors')
if (!provider.calls[1].ask.includes('ground')) fail('second ask does not name the ground net error')

const first = scorePlan(normalize(provider.calls[0].text), good.parts.map((p) => p.part))
const second = scorePlan(normalize(provider.calls[1].text), good.parts.map((p) => p.part))
if (first.ok) fail('the broken first attempt scored clean')
if (!second.ok) fail('the good second attempt did not score clean')

console.log('ok  2 calls captured')
console.log(`ok  attempt 1 dirty (${first.issues.filter((i) => i.level === 'error').length} errors), attempt 2 clean`)
console.log('ok  repair ask carries the errors:')
console.log('    ' + provider.calls[1].ask.split('\n').slice(0, 3).join('\n    '))
