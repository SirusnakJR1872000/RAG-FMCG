// The answer states of design brief §5.3, driven by §17 stream events.
import { describe, expect, it } from 'vitest'
import { applyEvent, citationProblem, endStream, newTurn, splitCitations, statusText,
  turnFromHistory } from './turns'

const run = (events, turn = newTurn('What is OOS?')) => events.reduce(applyEvent, turn)
const SOURCES = { event: 'sources', data: { sources: [{ n: 1, doc_code: 'ICH-Q7' }] } }

describe('applyEvent', () => {
  it('walks queued → searching → sources → streaming → answered', () => {
    let t = run([{ event: 'queued', data: { position: 2 } }])
    expect(statusText(t, 19)).toBe('Waiting — 2 questions ahead of you')
    t = run([{ event: 'queued', data: { position: 1 } }], t)
    expect(statusText(t, 19)).toBe('Waiting — 1 question ahead of you')
    t = run([{ event: 'status', data: { stage: 'retrieving' } }], t)
    expect(statusText(t, 19)).toBe('Searching 19 documents…')
    t = run([SOURCES], t)
    expect(t.sources).toHaveLength(1)
    expect(statusText(t)).toBe('Writing answer…') // sources arrive BEFORE the answer
    t = run([{ event: 'token', data: { t: 'OOS ' } }, { event: 'token', data: { t: 'must [1].' } }], t)
    expect(t.phase).toBe('streaming')
    expect(t.text).toBe('OOS must [1].')
    t = run([{ event: 'done', data: { event_id: 'evt_1', answer_type: 'answered',
      citation_check: { status: 'ok' }, latency_ms: { total: 64000 } } }], t)
    expect(t).toMatchObject({ phase: 'done', eventId: 'evt_1', answerType: 'answered' })
    expect(statusText(t)).toBe('')
  })

  it('shows "Understanding your question…" only for a follow-up rewrite', () => {
    expect(statusText(run([{ event: 'status', data: { stage: 'rewriting' } }])))
      .toBe('Understanding your question…')
  })

  it('a retrieval refusal: sources (maybe empty) then done, no tokens', () => {
    const t = run([{ event: 'sources', data: { sources: [] } },
      { event: 'done', data: { event_id: 'e', answer_type: 'retrieval_refusal' } }])
    expect(t).toMatchObject({ phase: 'done', answerType: 'retrieval_refusal', text: '' })
  })

  it('AUDIT_WRITE_FAILED becomes "not recorded" (the answer is hidden), others "error"', () => {
    const notRecorded = run([SOURCES, { event: 'token', data: { t: 'x' } },
      { event: 'error', data: { code: 'AUDIT_WRITE_FAILED', message: 'm', request_id: 'r1' } }])
    expect(notRecorded.phase).toBe('not_recorded')
    const failed = run([{ event: 'error', data: { code: 'LLM_TIMEOUT', message: 'slow',
      request_id: 'r2' } }])
    expect(failed).toMatchObject({ phase: 'error', error: { code: 'LLM_TIMEOUT', requestId: 'r2' } })
  })
})

describe('endStream', () => {
  it('a stream that stops mid-answer is "interrupted" and keeps the partial text', () => {
    const t = endStream(run([SOURCES, { event: 'token', data: { t: 'Half an' } }]))
    expect(t).toMatchObject({ phase: 'interrupted', text: 'Half an' })
  })

  it('a stream that stops before anything arrived is an error', () => {
    expect(endStream(newTurn('q')).phase).toBe('error')
  })

  it('leaves a finished turn alone', () => {
    const done = run([{ event: 'done', data: { event_id: 'e', answer_type: 'answered' } }])
    expect(endStream(done)).toBe(done)
  })
})

describe('helpers', () => {
  it('splits citation markers out of the text', () => {
    expect(splitCitations('A [1] and [12].')).toEqual(['A ', { n: 1 }, ' and ', { n: 12 }, '.'])
    expect(splitCitations('No citations')).toEqual(['No citations'])
    expect(splitCitations('[2]')).toEqual([{ n: 2 }])
  })

  it('flags only real citation problems', () => {
    expect(citationProblem({ status: 'ok', invalid: [] })).toBe(false)
    expect(citationProblem({ status: 'invalid', invalid: [7] })).toBe(true)
    expect(citationProblem(null)).toBe(false)
  })

  it('rebuilds a turn from a history detail', () => {
    const t = turnFromHistory({ event_id: 'evt_9', question: 'q', timestamp_utc: '2026-11-25T10:00:00Z',
      result: 'answered', answer: 'a [1]', answer_type: 'answered', sources: [{ n: 1 }],
      citation_check: { status: 'ok' }, latency_ms: { total: 5 }, feedback: { rating: -1 } })
    expect(t).toMatchObject({ phase: 'done', text: 'a [1]', eventId: 'evt_9', feedback: -1 })
    expect(turnFromHistory({ event_id: 'e', result: 'interrupted' }).phase).toBe('interrupted')
    expect(turnFromHistory({ event_id: 'e', result: 'failed', error_code: 'LLM_TIMEOUT' }))
      .toMatchObject({ phase: 'error', error: { code: 'LLM_TIMEOUT' } })
  })
})
