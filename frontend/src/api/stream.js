/**
 * Server-Sent Events over fetch (PROJECT_SPEC §17).
 *
 * EventSource is not used: it cannot send an Authorization header and only does GET. So the
 * response body is read with ReadableStream + TextDecoderStream and parsed here. Network chunks
 * do not respect event boundaries: one chunk may hold half an event, or several events.
 */

import { api } from './client'

/**
 * A push parser: feed it text as it arrives; it calls onEvent({event, data}) for each complete
 * event. Comment lines (": keep-alive") are ignored. `data` is parsed JSON (or the raw string if
 * it is not JSON).
 */
export function createSSEParser(onEvent) {
  let buffer = ''

  function dispatch(block) {
    let event = 'message'
    const dataLines = []
    for (const line of block.split('\n')) {
      if (line === '' || line.startsWith(':')) continue
      const colon = line.indexOf(':')
      const field = colon === -1 ? line : line.slice(0, colon)
      let value = colon === -1 ? '' : line.slice(colon + 1)
      if (value.startsWith(' ')) value = value.slice(1)
      if (field === 'event') event = value
      else if (field === 'data') dataLines.push(value)
    }
    if (dataLines.length === 0) return
    const text = dataLines.join('\n')
    let data
    try {
      data = JSON.parse(text)
    } catch {
      data = text
    }
    onEvent({ event, data })
  }

  return {
    push(text) {
      buffer += text.replace(/\r\n?/g, '\n')
      let end
      while ((end = buffer.indexOf('\n\n')) !== -1) {
        const block = buffer.slice(0, end)
        buffer = buffer.slice(end + 2)
        dispatch(block)
      }
    },
    /** The stream closed: a final event without its blank line still counts. */
    end() {
      if (buffer.trim()) dispatch(buffer)
      buffer = ''
    },
  }
}

/**
 * POST /api/query/stream and call onEvent for each event. Resolves when the stream ends.
 * Throws ApiError if the request is refused before streaming (403, 429 QUEUE_FULL, …), and
 * AbortError if `signal` aborts.
 */
export async function streamQuery({ question, conversationId, signal, onEvent }) {
  const response = await api('/api/query/stream', {
    method: 'POST',
    body: { question, conversation_id: conversationId ?? null },
    signal,
    raw: true,
  })
  const parser = createSSEParser(onEvent)
  const reader = response.body.pipeThrough(new TextDecoderStream()).getReader()
  try {
    for (;;) {
      const { value, done } = await reader.read()
      if (done) break
      parser.push(value)
    }
    parser.end()
  } finally {
    reader.releaseLock()
  }
}
