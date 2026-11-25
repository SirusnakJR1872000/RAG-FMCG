/**
 * The turns of the open conversation and asking a new question (PROJECT_SPEC §17, §18.2).
 *
 * Only one question runs at a time per user (the composer is disabled meanwhile). Leaving the
 * page aborts the stream; the backend then records the question as completed: false.
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../api/client'
import { streamQuery } from '../api/stream'
import { applyEvent, endStream, isFinished, newTurn } from './turns'

export function useStreamingQuery({ onAnswered } = {}) {
  const [turns, setTurns] = useState([])
  const [conversationId, setConversationId] = useState(null)
  const [running, setRunning] = useState(false)
  const controller = useRef(null)

  useEffect(() => () => controller.current?.abort(), [])

  const update = useCallback((key, fn) => {
    setTurns((all) => all.map((t) => (t.key === key ? fn(t) : t)))
  }, [])

  const ask = useCallback(async (question) => {
    const turn = newTurn(question)
    setTurns((all) => [...all, turn])
    setRunning(true)
    const abort = new AbortController()
    controller.current = abort
    let latest = turn
    const set = (fn) => {
      latest = fn(latest)
      update(turn.key, () => latest)
    }
    try {
      let id = conversationId
      if (!id) {
        id = (await api('/api/conversations', { method: 'POST', signal: abort.signal })).id
        setConversationId(id)
      }
      await streamQuery({ question, conversationId: id, signal: abort.signal,
        onEvent: (event) => set((t) => applyEvent(t, event)) })
      set((t) => endStream(t))
    } catch (err) {
      if (err?.name === 'AbortError') return
      set((t) => (isFinished(t) ? t : endStream(t, { code: err.code ?? 'NETWORK_ERROR',
        message: err.message ?? 'The connection was lost.', requestId: err.requestId ?? null })))
    } finally {
      if (controller.current === abort) controller.current = null
      setRunning(false)
      if (latest.phase === 'done') onAnswered?.(latest)
    }
  }, [conversationId, update, onAnswered])

  /** Open an earlier conversation (turns rebuilt from history), or a new empty one. */
  const open = useCallback((id, loadedTurns = []) => {
    controller.current?.abort()
    setRunning(false)
    setConversationId(id)
    setTurns(loadedTurns)
  }, [])

  const remove = useCallback((key) => setTurns((all) => all.filter((t) => t.key !== key)), [])

  return { turns, conversationId, running, ask, open, update, remove }
}
