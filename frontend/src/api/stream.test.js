// The stream parser (PROJECT_SPEC §18.2): events split across chunks, several per chunk.
import { describe, expect, it } from 'vitest'
import { createSSEParser } from './stream'

function collect(chunks, { end = true } = {}) {
  const events = []
  const parser = createSSEParser((e) => events.push(e))
  chunks.forEach((c) => parser.push(c))
  if (end) parser.end()
  return events
}

const STREAM =
  'event: status\ndata: {"stage": "retrieving"}\n\n' +
  'event: sources\ndata: {"sources": [{"n": 1, "doc_code": "ICH-Q7"}]}\n\n' +
  'event: token\ndata: {"t": "OOS "}\n\n' +
  'event: token\ndata: {"t": "results [1]."}\n\n' +
  'event: done\ndata: {"event_id": "evt_1", "answer_type": "answered"}\n\n'

describe('createSSEParser', () => {
  it('parses a whole stream delivered in one chunk, in order', () => {
    const events = collect([STREAM])
    expect(events.map((e) => e.event)).toEqual(['status', 'sources', 'token', 'token', 'done'])
    expect(events[1].data.sources[0].doc_code).toBe('ICH-Q7')
    expect(events.filter((e) => e.event === 'token').map((e) => e.data.t).join('')).toBe(
      'OOS results [1].')
  })

  it('gives the same events however the network splits the bytes', () => {
    const whole = collect([STREAM])
    for (const size of [1, 2, 3, 7, 13, 50]) {
      const chunks = []
      for (let i = 0; i < STREAM.length; i += size) chunks.push(STREAM.slice(i, i + size))
      expect(collect(chunks)).toEqual(whole)
    }
  })

  it('emits nothing until an event is complete', () => {
    const events = collect(['event: token\ndata: {"t": "hal'], { end: false })
    expect(events).toEqual([])
  })

  it('ignores keep-alive comments, including between the halves of an event', () => {
    const events = collect([': keep-alive\n\n', 'event: queued\n', 'data: {"position": 2}\n\n',
      ': keep-alive\n\n'])
    expect(events).toEqual([{ event: 'queued', data: { position: 2 } }])
  })

  it('accepts CRLF line endings and a missing space after the colon', () => {
    const events = collect(['event:token\r\ndata:{"t":"x"}\r\n\r\n'])
    expect(events).toEqual([{ event: 'token', data: { t: 'x' } }])
  })

  it('handles a CRLF pair split across two chunks', () => {
    const events = collect(['event: token\r\ndata: {"t":"x"}\r', '\n\r\n'])
    expect(events).toEqual([{ event: 'token', data: { t: 'x' } }])
  })

  it('joins multi-line data and keeps non-JSON data as text', () => {
    expect(collect(['data: line one\ndata: line two\n\n'])).toEqual([
      { event: 'message', data: 'line one\nline two' }])
  })

  it('delivers a last event that lacks the final blank line when the stream ends', () => {
    expect(collect(['event: error\ndata: {"code": "LLM_TIMEOUT"}'])).toEqual([
      { event: 'error', data: { code: 'LLM_TIMEOUT' } }])
  })
})
