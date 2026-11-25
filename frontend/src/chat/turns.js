/**
 * One question and its answer ("turn") as the stream events move it through the answer states
 * of the design brief §5.3 (1 queued … 11 interrupted). Pure functions, so they are unit-tested.
 */

export const NOT_COVERED_TEXT = "The approved documents don't cover this question."

export function newTurn(question) {
  return { key: `t_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`, question,
    askedAt: new Date().toISOString(), phase: 'sending', position: null, sources: [], text: '',
    answerType: null, citationCheck: null, latency: null, eventId: null, error: null,
    feedback: null }
}

/** Apply one SSE event (§17.1) to a turn; returns a new turn. */
export function applyEvent(turn, { event, data }) {
  switch (event) {
    case 'queued':
      return { ...turn, phase: 'queued', position: data.position }
    case 'status': {
      const phase = { rewriting: 'rewriting', retrieving: 'searching', reranking: 'searching',
        generating: 'writing' }[data.stage] ?? turn.phase
      return { ...turn, phase, position: null }
    }
    case 'sources':
      return { ...turn, phase: 'writing', sources: data.sources ?? [] }
    case 'token':
      return { ...turn, phase: 'streaming', text: turn.text + (data.t ?? '') }
    case 'done':
      return { ...turn, phase: 'done', answerType: data.answer_type,
        citationCheck: data.citation_check ?? null, latency: data.latency_ms ?? null,
        eventId: data.event_id }
    case 'error':
      return { ...turn, phase: data.code === 'AUDIT_WRITE_FAILED' ? 'not_recorded' : 'error',
        error: { code: data.code, message: data.message, requestId: data.request_id } }
    default:
      return turn
  }
}

export const isFinished = (turn) => ['done', 'error', 'not_recorded', 'interrupted']
  .includes(turn.phase)

/** The stream ended (or the connection dropped) without `done` or `error`. */
export function endStream(turn, failure = null) {
  if (isFinished(turn)) return turn
  if (turn.text || turn.sources.length) return { ...turn, phase: 'interrupted' }
  return { ...turn, phase: 'error', error: failure ?? { code: 'NETWORK_ERROR',
    message: 'The connection was lost before an answer arrived.' } }
}

/** What the status line says (§5.3; §18.2). `documentCount` is the active registry size. */
export function statusText(turn, documentCount) {
  switch (turn.phase) {
    case 'sending':
      return 'Sending your question…'
    case 'queued':
      if (!turn.position) return 'Starting…'
      return `Waiting — ${turn.position} question${turn.position === 1 ? '' : 's'} ahead of you`
    case 'rewriting':
      return 'Understanding your question…'
    case 'searching':
      return documentCount ? `Searching ${documentCount} documents…` : 'Searching documents…'
    case 'writing':
    case 'streaming':
      return 'Writing answer…'
    default:
      return ''
  }
}

export const isRefusal = (turn) => ['retrieval_refusal', 'model_refusal'].includes(turn.answerType)

/** True when the citation check flagged a problem (§9.4): invalid numbers or no citation. */
export function citationProblem(check) {
  return Boolean(check && check.status && check.status !== 'ok')
}

/** Split answer text into text and citation parts: "A [1] b" → ["A ", {n:1}, " b"]. */
export function splitCitations(text) {
  const parts = []
  const re = /\[(\d{1,2})\]/g
  let last = 0
  let m
  while ((m = re.exec(text)) !== null) {
    if (m.index > last) parts.push(text.slice(last, m.index))
    parts.push({ n: Number(m[1]) })
    last = m.index + m[0].length
  }
  if (last < text.length) parts.push(text.slice(last))
  return parts
}

/** A turn rebuilt from a history detail (GET /api/history/{id}), for an earlier conversation. */
export function turnFromHistory(detail) {
  const phase = detail.result === 'failed' ? 'error'
    : detail.result === 'interrupted' ? 'interrupted' : 'done'
  return { key: detail.event_id, question: detail.question, askedAt: detail.timestamp_utc, phase,
    position: null, sources: detail.sources ?? [], text: detail.answer ?? '',
    answerType: detail.answer_type, citationCheck: detail.citation_check ?? null,
    latency: detail.latency_ms ?? null, eventId: detail.event_id,
    error: phase === 'error' ? { code: detail.error_code, message: 'This question failed.' } : null,
    feedback: detail.feedback?.rating ?? null }
}
