// compose() only hands back the plan it settled on, but the attempts it threw
// away are the interesting data: a broken plan plus the errors it drew plus the
// fix is exactly what teaches a model to repair itself.
//
// It takes a provider though, so wrapping one gets every attempt out without
// changing anything in the product.

import { pickProvider } from '@solder/core'

export function recordingProvider(inner = pickProvider()) {
  const calls = []
  return {
    name: inner.name,
    model: inner.model,
    calls,
    system: null,
    async complete(req) {
      const t0 = Date.now()
      // the system prompt is 13k tokens and identical every call; SFT needs it
      // but the per-call record does not, so keep one copy
      if (this.system === null) this.system = req.system
      const reply = await inner.complete(req)
      calls.push({
        // the last user turn is the request on attempt 1 and the validator's
        // complaint on every attempt after it
        ask: req.messages[req.messages.length - 1]?.content ?? '',
        text: reply.text,
        refusal: reply.refusal ?? null,
        usage: reply.usage ?? null,
        ms: Date.now() - t0,
      })
      return reply
    },
  }
}
