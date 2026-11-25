// History: the user's own past questions (design brief §5.4). Read from the audit trail, so it
// always matches what was recorded.
import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, query } from '../api/client'
import AnswerText from '../chat/AnswerText'
import SourceCard from '../chat/SourceCard'
import Icon from '../components/Icon'
import { Badge, Card, Drawer, ErrorBlock, INPUT, KeyValueList, PageHeader, Pagination,
  SkeletonRows, Spinner, TD, TH } from '../components/ui'
import { localDateTime, seconds, truncate } from '../lib/format'

const PAGE_SIZE = 20

export const RESULT = {
  answered: { tone: 'success', text: 'Answered' },
  not_covered: { tone: 'neutral', text: 'Not covered' },
  failed: { tone: 'danger', text: 'Failed' },
  interrupted: { tone: 'warning', text: 'Interrupted' },
}

const FEEDBACK = { 1: '👍', '-1': '👎' }

function Detail({ eventId, onClose }) {
  const [detail, setDetail] = useState(null)
  const [error, setError] = useState(null)
  const [highlighted, setHighlighted] = useState(null)
  useEffect(() => {
    if (!eventId) return
    setDetail(null)
    setError(null)
    api(`/api/history/${eventId}`).then(setDetail).catch(setError)
  }, [eventId])
  const result = detail && (RESULT[detail.result] ?? RESULT.answered)
  return (
    <Drawer open={Boolean(eventId)} onClose={onClose} title="Question detail" width="max-w-3xl">
      <ErrorBlock error={error} />
      {!detail && !error && <Spinner />}
      {detail && (
        <div className="space-y-6">
          <KeyValueList items={[
            ['Asked', localDateTime(detail.timestamp_utc)],
            ['Result', <Badge key="r" tone={result.tone}>{result.text}</Badge>],
            ['Question', detail.question],
            detail.standalone_question && detail.standalone_question !== detail.question
              ? ['Understood as', detail.standalone_question] : null,
            ['Time taken', seconds(detail.time_taken_ms)],
            ['Feedback', detail.feedback ? `${FEEDBACK[detail.feedback.rating]} ${detail.feedback.comment ?? ''}` : '—'],
            detail.error_code ? ['Error', <code key="e" className="font-mono text-xs">{detail.error_code}</code>] : null,
          ]} />
          {detail.answer && (
            <section>
              <h3 className="mb-2 text-xs font-semibold uppercase tracking-widest text-muted">Answer</h3>
              <Card className="p-4">
                <AnswerText text={detail.answer} sources={detail.sources ?? []} onCite={setHighlighted} />
              </Card>
            </section>
          )}
          {detail.sources?.length > 0 && (
            <section>
              <h3 className="mb-2 text-xs font-semibold uppercase tracking-widest text-muted">
                Sources, as they were when answered ({detail.sources.length})
              </h3>
              <div className="space-y-3">
                {detail.sources.map((s) => (
                  <SourceCard key={s.n} source={s} highlighted={highlighted === s.n}
                    superseded={s.superseded} />
                ))}
              </div>
            </section>
          )}
        </div>
      )}
    </Drawer>
  )
}

export default function History() {
  const [search, setSearch] = useState('')
  const [q, setQ] = useState('')
  const [from, setFrom] = useState('')
  const [to, setTo] = useState('')
  const [page, setPage] = useState(1)
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const [open, setOpen] = useState(null)

  useEffect(() => {
    const id = setTimeout(() => { setQ(search.trim()); setPage(1) }, 300) // search as you type
    return () => clearTimeout(id)
  }, [search])

  const load = useCallback(async () => {
    setError(null)
    setData(null)
    try {
      setData(await api(`/api/history${query({ q, from, to, page, page_size: PAGE_SIZE })}`))
    } catch (err) {
      setError(err)
    }
  }, [q, from, to, page])
  useEffect(() => { load() }, [load])

  const filtered = q || from || to
  return (
    <div className="h-full overflow-y-auto px-4 py-8 lg:px-8">
      <div className="mx-auto max-w-6xl">
        <PageHeader label="Your activity" title="History" description="Your past questions and the answers you were given." />
        <div className="mb-4 flex flex-wrap items-end gap-3">
          <label className="relative min-w-60 flex-1">
            <span className="sr-only">Search questions</span>
            <Icon name="search" className="absolute left-3 top-1/2 -translate-y-1/2 text-muted" />
            <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search questions…"
              className={`${INPUT} pl-9`} />
          </label>
          <label className="text-sm">
            <span className="mb-1 block text-xs text-muted">From</span>
            <input type="date" value={from} max={to || undefined} onChange={(e) => { setFrom(e.target.value); setPage(1) }} className={INPUT} />
          </label>
          <label className="text-sm">
            <span className="mb-1 block text-xs text-muted">To</span>
            <input type="date" value={to} min={from || undefined} onChange={(e) => { setTo(e.target.value); setPage(1) }} className={INPUT} />
          </label>
        </div>
        <ErrorBlock error={error} onRetry={load} />
        <Card className="overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-surface-muted">
                <tr>
                  <th className={TH}>Date / time</th><th className={TH}>Question</th><th className={TH}>Result</th>
                  <th className={TH}>Sources</th><th className={TH}>Feedback</th><th className={TH}>Time taken</th>
                  <th className={TH}><span className="sr-only">Open</span></th>
                </tr>
              </thead>
              <tbody>
                {!data && !error && <SkeletonRows cols={7} />}
                {data?.items.map((item) => {
                  const r = RESULT[item.result] ?? RESULT.answered
                  return (
                    <tr key={item.event_id} onClick={() => setOpen(item.event_id)} tabIndex={0}
                      onKeyDown={(e) => e.key === 'Enter' && setOpen(item.event_id)}
                      className="cursor-pointer border-t border-line hover:bg-surface-muted">
                      <td className={`${TD} whitespace-nowrap text-muted`}>{localDateTime(item.timestamp_utc)}</td>
                      <td className={TD}>{truncate(item.question, 90)}</td>
                      <td className={TD}><Badge tone={r.tone}>{r.text}</Badge></td>
                      <td className={TD}>{item.sources_count}</td>
                      <td className={TD}>{FEEDBACK[item.feedback] ?? '—'}</td>
                      <td className={`${TD} whitespace-nowrap`}>{seconds(item.time_taken_ms)}</td>
                      <td className={`${TD} text-muted`}><Icon name="chevronRight" /></td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
          {data && data.total === 0 && (
            <div className="p-10 text-center text-muted">
              {filtered ? 'No questions match these filters.' : <>No questions yet. <Link to="/" className="text-primary hover:underline">Ask one in Chat</Link>.</>}
            </div>
          )}
          {data && data.total > 0 && (
            <Pagination page={page} pageSize={PAGE_SIZE} total={data.total} onPage={setPage} />
          )}
        </Card>
      </div>
      <Detail eventId={open} onClose={() => setOpen(null)} />
    </div>
  )
}
