// Chat (design brief §5.3; PROJECT_SPEC §18.2–18.3): conversations, the streaming answer and its
// sources. ≥1280 px: three columns. Narrower: the conversation list collapses behind a button and
// the sources open as a drawer when a citation is clicked.
import { useCallback, useEffect, useRef, useState } from 'react'
import { api, query } from '../api/client'
import AnswerBlock from '../chat/AnswerBlock'
import ConversationList, { groupConversations } from '../chat/ConversationList'
import SourceCard from '../chat/SourceCard'
import { turnFromHistory } from '../chat/turns'
import { useStreamingQuery } from '../chat/useStreamingQuery'
import Icon from '../components/Icon'
import { Button, Drawer, ErrorBlock, Spinner } from '../components/ui'
import { localDateTime } from '../lib/format'

const MAX_CHARS = 1000
const EXAMPLES = [
  'What must happen after an OOS result?',
  'How often is a Product Quality Review required?',
  'What does Annex 11 say about audit trails?',
  'Does our deviation SOP align with ICH Q10?',
]

function Composer({ onSend, disabled }) {
  const [text, setText] = useState('')
  const trimmed = text.trim()
  const valid = trimmed.length >= 3 && text.length <= MAX_CHARS
  function send() {
    if (!valid || disabled) return
    onSend(trimmed)
    setText('')
  }
  return (
    <div className="rounded-2xl border border-line bg-surface p-3 shadow-sm">
      <textarea value={text} onChange={(e) => setText(e.target.value)} rows={2}
        maxLength={MAX_CHARS} aria-label="Your question" disabled={disabled}
        placeholder="Ask a question about GMP or SOPs…"
        onKeyDown={(e) => {
          if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault()
            send()
          }
        }}
        className="w-full resize-none bg-transparent px-1 text-[15px] outline-none disabled:text-muted" />
      <div className="flex items-center justify-between">
        <span className="text-xs text-muted">{text.length}/{MAX_CHARS}</span>
        <Button onClick={send} disabled={!valid || disabled}>
          Send <Icon name="send" />
        </Button>
      </div>
    </div>
  )
}

function SourcesPanel({ turn, highlighted }) {
  const sources = turn?.sources ?? []
  return (
    <div>
      <h2 className="text-xs font-semibold uppercase tracking-widest text-muted">Sources ({sources.length})</h2>
      {sources.length > 0 && <p className="mt-1 text-xs text-muted">Only these passages were used to write the answer.</p>}
      {!turn && <p className="mt-3 text-sm text-muted">The passages behind each answer appear here, before the answer is written.</p>}
      {turn && sources.length === 0 && turn.phase !== 'sending' && (
        <p className="mt-3 text-sm text-muted">No passages were relevant enough to use.</p>
      )}
      <div className="mt-3 space-y-3">
        {sources.map((s) => <SourceCard key={s.n} source={s} highlighted={highlighted === s.n} />)}
      </div>
    </div>
  )
}

export default function Chat() {
  const [conversations, setConversations] = useState([])
  const [docCount, setDocCount] = useState(null)
  const [loadingConversation, setLoadingConversation] = useState(false)
  const [loadError, setLoadError] = useState(null)
  const [selected, setSelected] = useState(null) // turn key whose sources are shown
  const [highlighted, setHighlighted] = useState(null)
  const [listOpen, setListOpen] = useState(false)
  const [sourcesOpen, setSourcesOpen] = useState(false)
  const bottom = useRef(null)

  const refreshConversations = useCallback(async () => {
    try {
      const page = await api(`/api/history${query({ page_size: 100 })}`)
      setConversations(groupConversations(page.items))
    } catch {
      /* the list is a convenience; the chat still works */
    }
  }, [])

  const { turns, conversationId, running, ask, open, update, remove } = useStreamingQuery({
    onAnswered: refreshConversations })

  useEffect(() => {
    refreshConversations()
    api(`/api/documents${query({ status: 'active' })}`).then((d) => setDocCount(d.total)).catch(() => {})
  }, [refreshConversations])

  const latest = turns[turns.length - 1]
  const shown = turns.find((t) => t.key === selected) ?? latest
  useEffect(() => {
    bottom.current?.scrollIntoView?.({ block: 'end' })
  }, [turns.length, latest?.text])

  function send(question) {
    setSelected(null) // follow the newest answer
    setHighlighted(null)
    ask(question)
  }

  async function openConversation(id) {
    setListOpen(false)
    setLoadError(null)
    setLoadingConversation(true)
    try {
      const page = await api(`/api/history${query({ conversation: id, page_size: 100 })}`)
      const items = [...page.items].reverse() // oldest first
      const details = await Promise.all(items.map((i) => api(`/api/history/${i.event_id}`)))
      open(id, details.map(turnFromHistory))
      setSelected(null)
      setHighlighted(null)
    } catch (err) {
      setLoadError(err)
    } finally {
      setLoadingConversation(false)
    }
  }

  function newChat() {
    open(null, [])
    setSelected(null)
    setHighlighted(null)
    setListOpen(false)
  }

  function cite(turn, n) {
    setSelected(turn.key)
    setHighlighted(n)
    if (!window.matchMedia?.('(min-width: 1280px)').matches) setSourcesOpen(true)
  }

  function retry(turn) {
    remove(turn.key)
    send(turn.question)
  }

  const list = (
    <ConversationList conversations={conversations} activeId={conversationId}
      onOpen={openConversation} onNew={newChat} disabled={running} />
  )

  return (
    <div className="flex h-full min-h-0">
      {/* conversations: a column on wide screens, a drawer below 1280 px */}
      <aside className="hidden w-60 shrink-0 border-r border-line bg-surface/70 xl:block">{list}</aside>
      <Drawer open={listOpen} onClose={() => setListOpen(false)} title="Conversations" width="max-w-xs">
        {list}
      </Drawer>

      <section className="flex min-w-0 flex-1 flex-col">
        <div className="flex items-center gap-2 px-4 pt-3 xl:hidden">
          <Button variant="secondary" onClick={() => setListOpen(true)}><Icon name="menu" /> Conversations</Button>
          {shown && (
            <Button variant="secondary" onClick={() => setSourcesOpen(true)}>
              <Icon name="sources" /> Sources ({shown.sources.length})
            </Button>
          )}
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto px-4 py-6 lg:px-8">
          <div className="mx-auto max-w-3xl space-y-6">
            <ErrorBlock error={loadError} />
            {loadingConversation && <div className="grid place-items-center py-10 text-muted"><Spinner /></div>}
            {!loadingConversation && turns.length === 0 && (
              <div className="py-10 text-center">
                <div className="text-xs font-semibold uppercase tracking-widest text-muted">Controlled knowledge base</div>
                <h1 className="mt-2 text-3xl font-bold tracking-tight">Ask about GMP and SOPs</h1>
                <p className="mx-auto mt-2 max-w-lg text-muted">
                  Answers come only from the approved documents{docCount ? ` (${docCount} active)` : ''}, with the
                  passages they are based on.
                </p>
                <div className="mt-6 flex flex-wrap justify-center gap-2">
                  {EXAMPLES.map((q) => (
                    <button key={q} type="button" onClick={() => send(q)} disabled={running}
                      className="rounded-full border border-line bg-surface px-4 py-2 text-sm hover:border-primary hover:text-primary-ink">
                      {q}
                    </button>
                  ))}
                </div>
              </div>
            )}
            {turns.map((turn) => (
              <div key={turn.key} className="space-y-3">
                <div className="flex justify-end">
                  <div className="max-w-[85%] rounded-2xl border border-line bg-surface-muted px-4 py-3" data-testid="question">
                    <p className="whitespace-pre-line">{turn.question}</p>
                    <p className="mt-1 text-right text-xs text-muted">{localDateTime(turn.askedAt)}</p>
                  </div>
                </div>
                <AnswerBlock turn={turn} documentCount={docCount}
                  onCite={(n) => cite(turn, n)}
                  onRetry={running ? null : () => retry(turn)}
                  onRated={(rating) => update(turn.key, (t) => ({ ...t, feedback: rating }))} />
              </div>
            ))}
            <div ref={bottom} />
          </div>
        </div>
        <div className="px-4 pb-4 lg:px-8">
          <div className="mx-auto max-w-3xl">
            <Composer onSend={send} disabled={running} />
            <p className="mt-2 text-center text-xs text-muted">
              Responses use approved documents only. Do not use as a substitute for quality review.
            </p>
          </div>
        </div>
      </section>

      <aside className="hidden w-[360px] shrink-0 overflow-y-auto border-l border-line bg-surface/70 p-4 xl:block"
        aria-label="Sources">
        <SourcesPanel turn={shown} highlighted={highlighted} />
      </aside>
      <Drawer open={sourcesOpen} onClose={() => setSourcesOpen(false)} title="Sources" width="max-w-md">
        <SourcesPanel turn={shown} highlighted={highlighted} />
      </Drawer>
    </div>
  )
}
