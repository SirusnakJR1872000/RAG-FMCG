// The answer to one question, in all its states (design brief §5.3 states 1–11).
import { useState } from 'react'
import { api } from '../api/client'
import Icon from '../components/Icon'
import { useToast } from '../components/Toasts'
import { Badge, Button } from '../components/ui'
import { seconds } from '../lib/format'
import AnswerText from './AnswerText'
import { NOT_COVERED_TEXT, citationProblem, isRefusal, statusText } from './turns'

function Feedback({ turn, onRated }) {
  const notify = useToast()
  const [askComment, setAskComment] = useState(false)
  const [comment, setComment] = useState('')
  const [busy, setBusy] = useState(false)
  async function send(rating, text = null) {
    setBusy(true)
    try {
      await api('/api/feedback', { method: 'POST', body: { query_event_id: turn.eventId, rating,
        comment: text || null } })
      onRated(rating)
      setAskComment(false)
      notify('Feedback saved.')
    } catch (err) {
      notify(err.message, 'error')
    } finally {
      setBusy(false)
    }
  }
  const btn = (active) => `rounded-lg p-1.5 ${active ? 'bg-primary-subtle text-primary-ink' : 'text-muted hover:bg-surface-muted hover:text-ink'}`
  return (
    <>
      <button type="button" className={btn(turn.feedback === 1)} disabled={busy}
        onClick={() => send(1)} aria-label="Helpful" aria-pressed={turn.feedback === 1}>
        <Icon name="thumbUp" />
      </button>
      <button type="button" className={btn(turn.feedback === -1)} disabled={busy}
        onClick={() => setAskComment(!askComment)} aria-label="Not helpful" aria-pressed={turn.feedback === -1}>
        <Icon name="thumbDown" />
      </button>
      {askComment && (
        <div className="mt-2 w-full space-y-2">
          <textarea value={comment} maxLength={1000} rows={2} onChange={(e) => setComment(e.target.value)}
            placeholder="What was wrong? (optional)" aria-label="Feedback comment"
            className="w-full rounded-xl border border-line p-2 text-sm outline-none focus:border-primary" />
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setAskComment(false)}>Cancel</Button>
            <Button busy={busy} onClick={() => send(-1, comment)}>Send feedback</Button>
          </div>
        </div>
      )}
    </>
  )
}

export default function AnswerBlock({ turn, documentCount, onCite, onRetry, onRated }) {
  const [copied, setCopied] = useState(false)
  const status = statusText(turn, documentCount)

  if (turn.phase === 'not_recorded') {
    return (
      <div role="alert" className="rounded-2xl border border-red-200 bg-danger-bg p-4 text-sm text-danger">
        <p>This answer couldn&apos;t be recorded, so it wasn&apos;t shown. Please try again.</p>
        <div className="mt-3 flex items-center justify-between">
          {turn.error?.requestId && <span className="font-mono text-xs">Reference: {turn.error.requestId}</span>}
          <Button variant="secondary" onClick={onRetry}>Try again</Button>
        </div>
      </div>
    )
  }
  if (turn.phase === 'error') {
    return (
      <div role="alert" className="rounded-2xl border border-red-200 bg-danger-bg p-4 text-sm text-danger">
        <p className="flex items-center gap-2"><Icon name="alert" /> {turn.error?.message ?? 'Something went wrong.'}</p>
        <div className="mt-3 flex items-center justify-between gap-3">
          <span className="font-mono text-xs">{turn.error?.requestId ? `Reference: ${turn.error.requestId}` : ''}</span>
          {onRetry && <Button variant="secondary" onClick={onRetry}>Try again</Button>}
        </div>
      </div>
    )
  }
  if (turn.phase === 'done' && isRefusal(turn)) {
    return (
      <div className="rounded-2xl border border-line bg-info-bg p-4 text-sm text-info" data-testid="not-covered">
        <p className="flex items-center gap-2 font-medium"><Icon name="info" /> {NOT_COVERED_TEXT}</p>
        <p className="mt-1">Try rephrasing, or name the document or topic you mean.</p>
        {turn.eventId && (
          <div className="mt-3 flex flex-wrap items-center gap-1 border-t border-slate-200 pt-2">
            <Feedback turn={turn} onRated={onRated} />
          </div>
        )}
      </div>
    )
  }

  const answered = turn.phase === 'done'
  const interrupted = turn.phase === 'interrupted'
  const problem = answered && citationProblem(turn.citationCheck)
  async function copy() {
    try {
      await navigator.clipboard.writeText(turn.text)
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    } catch { /* clipboard blocked */ }
  }
  return (
    <div className="overflow-hidden rounded-2xl border border-line bg-surface shadow-sm" data-testid="answer">
      <div className="p-5">
        {status && (
          <div className="mb-3" aria-live="polite">
            <p className="flex items-center gap-2 text-sm text-muted" data-testid="status-line">{status}</p>
            {(turn.phase === 'queued' || turn.phase === 'sending' || turn.phase === 'searching'
              || turn.phase === 'rewriting' || (turn.phase === 'writing' && !turn.text)) && (
              <div className="mt-2 h-1 overflow-hidden rounded-full bg-primary-subtle">
                <div className="progress-slide h-full w-1/3 rounded-full bg-primary" />
              </div>
            )}
          </div>
        )}
        {problem && (
          <Badge tone="warning" className="mb-3"><Icon name="alert" size={14} /> Some citations couldn&apos;t be verified</Badge>
        )}
        {turn.text && (
          <div className={interrupted ? 'text-muted' : ''}>
            <AnswerText text={turn.text} sources={turn.sources} onCite={onCite}
              streaming={turn.phase === 'streaming'} />
          </div>
        )}
        {interrupted && (
          <div className="mt-3 flex items-center justify-between rounded-xl bg-info-bg p-3 text-sm text-info">
            <span>Answer interrupted.</span>
            {onRetry && <Button variant="secondary" onClick={onRetry}>Ask again</Button>}
          </div>
        )}
      </div>
      {answered && (
        <>
          <div className="flex items-center gap-2 bg-success-bg px-5 py-2 text-sm text-success">
            <Icon name="shield" /> Verify against the cited source before acting.
          </div>
          <div className="flex flex-wrap items-center gap-1 border-t border-line px-4 py-2 text-sm text-muted">
            {turn.eventId && <Feedback turn={turn} onRated={onRated} />}
            <span className="ml-2 inline-flex items-center gap-1"><Icon name="clock" size={14} />{seconds(turn.latency?.total)}</span>
            <button type="button" onClick={copy} className="ml-auto inline-flex items-center gap-1 rounded-lg px-2 py-1 hover:bg-surface-muted hover:text-ink">
              <Icon name={copied ? 'check' : 'copy'} size={14} /> {copied ? 'Copied' : 'Copy answer'}
            </button>
          </div>
        </>
      )}
    </div>
  )
}
