// Builds a prompt set by combining real catalog parts, so the expected part
// list is exact rather than something a model guessed at. Phrasing comes from
// templates, which is the weak spot: these read more uniform than a person
// writing in a box. The 40 hand-written prompts stay held out as eval for that
// reason, and are never generated over.
//
//   node node/prompts.mjs --n=2000 --out=data/prompts.json

import { writeFileSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import { byId } from '@solder/core'

const flags = Object.fromEntries(
  process.argv
    .slice(2)
    .filter((a) => a.startsWith('--'))
    .map((a) => {
      const [k, v] = a.replace(/^--/, '').split('=')
      return [k, v ?? true]
    }),
)
const N = Number(flags.n ?? 500)
const OUT = flags.out ?? 'data/prompts.json'
const VH = join(process.env.HOME, 'coding/portfolio/ui/tools/svgs/vector-hardware')

const cat = {}
for (const [id, p] of Object.entries(byId)) (cat[p.category] ??= []).push(id)

// a short name a person would type, taken off the catalog title so it cannot
// drift from the catalog itself
const shortName = (id) => {
  const t = byId[id].title
  return t.length > 34 ? t.split(' ').slice(0, 4).join(' ') : t
}

function mulberry32(a) {
  return function () {
    a |= 0
    a = (a + 0x6d2b79f5) | 0
    let t = Math.imul(a ^ (a >>> 15), 1 | a)
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

const pick = (rng, xs) => xs[Math.floor(rng() * xs.length)]
const sample = (rng, xs, k) => {
  const out = []
  const pool = [...xs]
  for (let i = 0; i < k && pool.length; i++) out.push(...pool.splice(Math.floor(rng() * pool.length), 1))
  return out
}

const SMALL_BRAINS = ['pi-pico', 'esp32-devkit', 'arduino-nano', 'stm32-blue-pill']
const OUTPUTS = [...cat.displays, 'buzzer', 'led', 'neopixel-ring', 'relay-module']

// which layouts a given mix can honestly be built in
function layoutsFor(parts) {
  const has = (id) => parts.includes(id)
  const out = ['plate', 'freeform']
  if (parts.length <= 8 && !has('raspberry-pi') && !has('jetson-nano')) out.push('breadboard')
  if (has('robot-chassis')) out.push('chassis')
  if (parts.some((p) => ['servo', 'dc-motor', 'a4988-driver', 'brushless-motor'].includes(p))) out.push('bracket')
  if (has('raspberry-pi')) out.push('stack')
  return out
}

const PHRASE = {
  breadboard: ['on a breadboard', 'breadboarded', 'as a solderless prototype'],
  plate: ['mounted flat on one plate', 'on a single perfboard', 'laid out on a plate'],
  chassis: ['on a rover chassis', 'built onto a small robot frame'],
  bracket: ['on a bracket with the moving parts exposed', 'as a small mechanism'],
  stack: ['as a stacked pi hat', 'stacked on the pi header'],
  freeform: ['', 'wired up loosely'],
}

const OPENERS = [
  (body, where) => `${body} ${where}`.trim(),
  (body, where) => `build ${body} ${where}`.trim(),
  (body, where) => `i want ${body} ${where}`.trim(),
  (body, where) => `${where ? where + ': ' : ''}${body}`.trim(),
  (body, where) => `a small project ${where}: ${body}`.trim(),
]

function one(rng) {
  const heavy = rng() < 0.25
  const brain = heavy ? pick(rng, cat.brains) : pick(rng, SMALL_BRAINS)
  const sensors = sample(rng, cat.sensors, 1 + Math.floor(rng() * 3))
  const outs = sample(rng, OUTPUTS, rng() < 0.15 ? 0 : 1 + Math.floor(rng() * 2))
  const extra = []
  if (rng() < 0.3) extra.push(pick(rng, cat.power))
  if (rng() < 0.2) extra.push(pick(rng, cat.motion))
  if (rng() < 0.15) extra.push(pick(rng, cat.wireless))
  if (rng() < 0.12) extra.push('robot-chassis', 'dc-motor')

  const parts = [...new Set([brain, ...sensors, ...outs, ...extra])]
  const layout = pick(rng, layoutsFor(parts))

  const list = (xs) =>
    xs.length < 2 ? xs.map(shortName).join('') : xs.slice(0, -1).map(shortName).join(', ') + ' and ' + shortName(xs.at(-1))

  let body = `${shortName(brain)} reading ${list(sensors)}`
  if (outs.length) body += `, ${rng() < 0.5 ? 'showing it on' : 'driving'} ${list(outs)}`
  if (extra.length) body += `, powered from ${list(extra.filter((e) => byId[e].category === 'power'))}`.replace(/ powered from $/, '')
  const rest = extra.filter((e) => byId[e].category !== 'power')
  if (rest.length) body += `, plus ${list(rest)}`

  return {
    id: '',
    layout,
    prompt: pick(rng, OPENERS)(body, pick(rng, PHRASE[layout])).replace(/\s+/g, ' ').trim(),
    expect: parts,
  }
}

const held = new Set(
  JSON.parse(readFileSync(join(VH, 'packages/core/evals/prompts.json'), 'utf8')).map((p) => p.prompt),
)

const rng = mulberry32(Number(flags.seed ?? 1))
const seen = new Set()
const out = []
let guard = 0
while (out.length < N && guard++ < N * 50) {
  const p = one(rng)
  if (seen.has(p.prompt) || held.has(p.prompt)) continue
  seen.add(p.prompt)
  p.id = `gen-${String(out.length).padStart(5, '0')}`
  out.push(p)
}

writeFileSync(OUT, JSON.stringify(out, null, 1))
const byLayout = {}
for (const p of out) byLayout[p.layout] = (byLayout[p.layout] ?? 0) + 1
console.log(`${out.length} prompts -> ${OUT}`)
console.log('by layout:', byLayout)
console.log('avg expect:', (out.reduce((a, p) => a + p.expect.length, 0) / out.length).toFixed(1))
