// Audit trail (design brief §5.6; PROJECT_SPEC §14, FR-10). Verifying and exporting are
// themselves recorded by the backend (AUDIT_VERIFIED, AUDIT_EXPORTED).
import { useCallback, useEffect, useRef, useState } from 'react'
import { api, query } from '../api/client'
import { useSystem } from '../auth/SystemStatus'
import Icon from '../components/Icon'
import { useToast } from '../components/Toasts'
import { Badge, Button, Card, CodeValue, Dialog, Drawer, INPUT, INPUT_BASE, KeyValueList, PageHeader,
  Pagination, SkeletonRows, ErrorBlock, TD, TH } from '../components/ui'
import { localDateTime, seconds, shortHash } from '../lib/format'

const PAGE_SIZE = 50

export const EVENT_GROUPS = {
  Access: ['LOGIN_SUCCESS', 'LOGIN_FAILED', 'ACCOUNT_LOCKED', 'LOGOUT', 'PASSWORD_CHANGED',
    'ACCESS_DENIED', 'REFRESH_REUSE_DETECTED'],
  Queries: ['QUERY', 'QUERY_FAILED', 'FEEDBACK'],
  Documents: ['DOCUMENT_INGESTED', 'DOCUMENT_SUPERSEDED', 'DOCUMENT_WITHDRAWN', 'INDEX_BUILT',
    'INDEX_ACTIVATED'],
  Users: ['USER_CREATED', 'USER_ROLE_CHANGED', 'USER_DEACTIVATED', 'USER_UNLOCKED'],
  System: ['SYSTEM_START', 'AUDIT_VERIFIED', 'AUDIT_EXPORTED'],
}
const GROUP_TONE = { Access: 'primary', Queries: 'success', Documents: 'fictional', Users: 'warning',
  System: 'neutral' }
export const FAILURES = new Set(['LOGIN_FAILED', 'ACCESS_DENIED', 'QUERY_FAILED',
  'REFRESH_REUSE_DETECTED'])

export function groupOf(eventType) {
  return Object.keys(EVENT_GROUPS).find((g) => EVENT_GROUPS[g].includes(eventType)) ?? 'System'
}

function EventBadge({ type }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      {FAILURES.has(type) && <span className="h-2 w-2 rounded-full bg-red-600" title="Failure" aria-label="Failure" />}
      <Badge tone={GROUP_TONE[groupOf(type)]} className="font-mono">{type}</Badge>
    </span>
  )
}

function EventTypePicker({ value, onChange }) {
  const [open, setOpen] = useState(false)
  const box = useRef(null)
  useEffect(() => {
    if (!open) return undefined
    const close = (e) => { if (!box.current?.contains(e.target)) setOpen(false) }
    document.addEventListener('mousedown', close)
    return () => document.removeEventListener('mousedown', close)
  }, [open])
  const toggle = (t) => onChange(value.includes(t) ? value.filter((v) => v !== t) : [...value, t])
  const toggleGroup = (g) => {
    const all = EVENT_GROUPS[g].every((t) => value.includes(t))
    onChange(all ? value.filter((t) => !EVENT_GROUPS[g].includes(t))
      : [...new Set([...value, ...EVENT_GROUPS[g]])])
  }
  return (
    <div className="relative" ref={box}>
      <button type="button" onClick={() => setOpen(!open)} aria-expanded={open}
        className={`${INPUT_BASE} flex w-auto items-center gap-2`}>
        Event type{value.length ? ` (${value.length})` : ': all'} <Icon name="chevronDown" size={14} />
      </button>
      {open && (
        <div className="absolute left-0 z-30 mt-2 grid max-h-96 w-[34rem] max-w-[90vw] grid-cols-2 gap-4 overflow-y-auto rounded-xl border border-line bg-surface p-4 shadow-lg">
          {Object.entries(EVENT_GROUPS).map(([g, types]) => (
            <fieldset key={g}>
              <legend>
                <label className="flex items-center gap-2 text-xs font-semibold uppercase tracking-widest text-muted">
                  <input type="checkbox" checked={types.every((t) => value.includes(t))} onChange={() => toggleGroup(g)} />{g}
                </label>
              </legend>
              {types.map((t) => (
                <label key={t} className="mt-1 flex items-center gap-2 font-mono text-xs">
                  <input type="checkbox" checked={value.includes(t)} onChange={() => toggle(t)} />{t}
                </label>
              ))}
            </fieldset>
          ))}
          {value.length > 0 && (
            <div className="col-span-2 text-right">
              <Button variant="ghost" onClick={() => onChange([])}>Clear</Button>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function IntegrityPanel({ integrity, verifying, onVerify, total }) {
  const broken = integrity && !integrity.ok
  return (
    <Card className={`mb-6 flex flex-wrap items-center gap-4 p-5 ${broken ? 'border-red-300 bg-danger-bg' : ''}`}
      data-testid="integrity-panel">
      <span className={`grid h-11 w-11 place-items-center rounded-xl ${broken ? 'bg-red-100 text-danger'
        : integrity ? 'bg-success-bg text-success' : 'bg-info-bg text-info'}`}>
        <Icon name={broken ? 'alert' : 'shield'} size={22} />
      </span>
      <div className="min-w-0 flex-1" aria-live="polite">
        <div className="font-semibold">
          {verifying ? `Checking ${total ? total.toLocaleString() : 'all'} records…`
            : !integrity ? 'Integrity not checked yet in this session'
              : integrity.ok ? `✓ Chain intact — ${integrity.checked.toLocaleString()} records`
                : `✗ Broken at record #${integrity.first_bad_seq}`}
        </div>
        <div className={`text-sm ${broken ? 'text-danger' : 'text-muted'}`}>
          {broken ? `${integrity.reason ?? 'A record was changed or removed.'} Records from #${integrity.first_bad_seq} on cannot be trusted.`
            : integrity?.verified_at ? `Last verified ${localDateTime(integrity.verified_at)}`
              : 'Recomputes every record’s hash and checks the links between them.'}
        </div>
      </div>
      <Button onClick={onVerify} busy={verifying}><Icon name="refresh" /> Verify now</Button>
    </Card>
  )
}

function Payload({ entry }) {
  const p = entry.payload ?? {}
  if (entry.event_type === 'QUERY') {
    return (
      <div className="space-y-4">
        <KeyValueList items={[
          ['Question', p.original_question],
          p.standalone_question && p.standalone_question !== p.original_question ? ['Understood as', p.standalone_question] : null,
          ['Answer type', p.answer_type],
          ['Completed', p.completed === false ? 'No (interrupted)' : 'Yes'],
          ['Conversation', p.conversation_id ? <CodeValue key="c" value={p.conversation_id} /> : '—'],
          ['Citation check', p.citation_check?.status ?? '—'],
          ['Model', p.models?.llm ?? p.llm?.model],
          ['Index build', p.index_build_id ? <CodeValue key="i" value={p.index_build_id} /> : '—'],
          ['Total time', seconds(p.latency_ms?.total)],
        ]} />
        {p.answer && <div className="whitespace-pre-line rounded-xl bg-surface-muted p-3 text-sm">{p.answer}</div>}
        {p.sources?.length > 0 && (
          <table className="w-full text-xs">
            <thead><tr className="text-left text-muted"><th className="py-1">#</th><th>Document</th><th>Version</th><th>Section</th><th>Score</th></tr></thead>
            <tbody>
              {p.sources.map((s, i) => (
                <tr key={s.n} className="border-t border-line">
                  <td className="py-1">[{s.n}]</td><td className="font-mono">{s.doc_code}</td><td>{s.version}</td>
                  <td>{s.section ?? '—'}</td><td>{p.reranker_scores?.[i]?.toFixed?.(2) ?? '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    )
  }
  const items = Object.entries(p).map(([k, v]) => [k.replace(/_/g, ' '),
    v !== null && typeof v === 'object' ? <code key={k} className="font-mono text-xs">{JSON.stringify(v)}</code> : String(v)])
  return items.length ? <KeyValueList items={items} /> : <p className="text-sm text-muted">No details.</p>
}

function Detail({ entry, onClose }) {
  const [raw, setRaw] = useState(false)
  return (
    <Drawer open={Boolean(entry)} onClose={onClose} title={entry ? `Record #${entry.seq}` : ''} width="max-w-3xl">
      {entry && (
        <div className="space-y-6">
          <KeyValueList items={[
            ['Event', <EventBadge key="e" type={entry.event_type} />],
            ['Summary', entry.summary],
            ['Time', <span key="t" title={entry.timestamp_utc}>{localDateTime(entry.timestamp_utc)} <span className="text-muted">({entry.timestamp_utc} UTC)</span></span>],
            ['User', `${entry.username}${entry.role ? ` (${entry.role})` : ''}`],
            ['IP address', entry.client_ip ?? '—'],
            ['Request id', entry.request_id ? <CodeValue key="r" value={entry.request_id} /> : '—'],
            ['Event id', <CodeValue key="i" value={entry.event_id} />],
            ['Record hash', <CodeValue key="h" value={entry.row_hash} display={shortHash(entry.row_hash, 16)} />],
            ['Previous hash', <CodeValue key="p" value={entry.prev_hash} display={shortHash(entry.prev_hash, 16)} />],
          ]} />
          <section>
            <div className="mb-2 flex items-center justify-between">
              <h3 className="text-xs font-semibold uppercase tracking-widest text-muted">Details</h3>
              <Button variant="ghost" onClick={() => setRaw(!raw)}>{raw ? 'Readable view' : 'Raw JSON'}</Button>
            </div>
            {raw ? <pre className="overflow-x-auto rounded-xl bg-slate-900 p-4 font-mono text-xs text-slate-100">{JSON.stringify(entry.payload, null, 2)}</pre>
              : <Payload entry={entry} />}
          </section>
        </div>
      )}
    </Drawer>
  )
}

export default function Audit() {
  const notify = useToast()
  const { integrity, setIntegrity } = useSystem()
  const [filters, setFilters] = useState({ from: '', to: '', user: '', event_type: [], result: '' })
  const [userText, setUserText] = useState('')
  const [page, setPage] = useState(1)
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const [open, setOpen] = useState(null)
  const [verifying, setVerifying] = useState(false)
  const [confirmExport, setConfirmExport] = useState(false)
  const [exporting, setExporting] = useState(false)

  const set = (patch) => { setFilters((f) => ({ ...f, ...patch })); setPage(1) }
  useEffect(() => {
    const id = setTimeout(() => set({ user: userText.trim() }), 300)
    return () => clearTimeout(id)
  }, [userText])

  const load = useCallback(async () => {
    setError(null)
    setData(null)
    try {
      setData(await api(`/api/audit/log${query({ ...filters, page, page_size: PAGE_SIZE })}`))
    } catch (err) {
      setError(err)
    }
  }, [filters, page])
  useEffect(() => { load() }, [load])

  async function verifyNow() {
    setVerifying(true)
    try {
      const result = await api('/api/audit/verify', { method: 'POST' })
      setIntegrity(result)
      if (!result.ok) notify(`Integrity check failed at record #${result.first_bad_seq}.`, 'error')
      load() // the check itself is now a record
    } catch (err) {
      notify(err.message, 'error')
    } finally {
      setVerifying(false)
    }
  }

  async function doExport() {
    setExporting(true)
    try {
      const response = await api(`/api/audit/export${query({ ...filters, format: 'json' })}`, { raw: true })
      const blob = await response.blob()
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `audit_export_${new Date().toISOString().slice(0, 19).replace(/[:T]/g, '-')}.json`
      a.click()
      URL.revokeObjectURL(url)
      notify('Export ready.')
      setConfirmExport(false)
      load()
    } catch (err) {
      notify(err.message, 'error')
    } finally {
      setExporting(false)
    }
  }

  const filtered = filters.from || filters.to || filters.user || filters.event_type.length || filters.result
  return (
    <div className="h-full overflow-y-auto px-4 py-8 lg:px-8">
      <div className="mx-auto max-w-7xl">
        <PageHeader label="Compliance" title="Audit trail"
          description="Every recorded action, hash-chained so that any change can be detected."
          action={<Button variant="secondary" onClick={() => setConfirmExport(true)} disabled={!data || data.total === 0}>
            <Icon name="download" /> Export JSON</Button>} />
        <IntegrityPanel integrity={integrity} verifying={verifying} onVerify={verifyNow}
          total={filtered ? null : data?.total} />
        <div className="mb-4 flex flex-wrap items-end gap-3">
          <label className="text-sm"><span className="mb-1 block text-xs text-muted">From</span>
            <input type="date" value={filters.from} onChange={(e) => set({ from: e.target.value })} className={INPUT} /></label>
          <label className="text-sm"><span className="mb-1 block text-xs text-muted">To</span>
            <input type="date" value={filters.to} onChange={(e) => set({ to: e.target.value })} className={INPUT} /></label>
          <label className="text-sm"><span className="mb-1 block text-xs text-muted">User</span>
            <input value={userText} onChange={(e) => setUserText(e.target.value)} placeholder="username" className={`${INPUT_BASE} w-40`} /></label>
          <EventTypePicker value={filters.event_type} onChange={(v) => set({ event_type: v })} />
          <select value={filters.result} onChange={(e) => set({ result: e.target.value })} className={`${INPUT_BASE} w-auto`} aria-label="Result">
            <option value="">Success and failure</option><option value="success">Success</option><option value="failure">Failure</option>
          </select>
        </div>
        <ErrorBlock error={error} onRetry={load} />
        <Card className="overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-surface-muted">
                <tr><th className={TH}>#</th><th className={TH}>Time</th><th className={TH}>User</th><th className={TH}>Role</th>
                  <th className={TH}>Event</th><th className={TH}>Summary</th><th className={TH}>IP</th></tr>
              </thead>
              <tbody>
                {!data && !error && <SkeletonRows cols={7} />}
                {data?.items.map((e) => (
                  <tr key={e.seq} onClick={() => setOpen(e)} tabIndex={0} onKeyDown={(k) => k.key === 'Enter' && setOpen(e)}
                    className={`cursor-pointer border-t border-line hover:bg-surface-muted ${
                      integrity && !integrity.ok && e.seq >= integrity.first_bad_seq ? 'bg-danger-bg' : ''}`}>
                    <td className={`${TD} font-mono text-xs text-muted`}>{e.seq}</td>
                    <td className={`${TD} whitespace-nowrap`} title={`${e.timestamp_utc} UTC`}>{localDateTime(e.timestamp_utc)}</td>
                    <td className={TD}>{e.username}</td>
                    <td className={`${TD} text-muted`}>{e.role ?? '—'}</td>
                    <td className={TD}><EventBadge type={e.event_type} /></td>
                    <td className={TD}>{e.summary}</td>
                    <td className={`${TD} font-mono text-xs text-muted`}>{e.client_ip ?? '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {data && data.total === 0 && <p className="p-10 text-center text-muted">No records match these filters.</p>}
          {data && data.total > 0 && <Pagination page={page} pageSize={PAGE_SIZE} total={data.total} onPage={setPage} />}
        </Card>
      </div>
      <Detail entry={open} onClose={() => setOpen(null)} />
      <Dialog open={confirmExport} onClose={() => setConfirmExport(false)} title="Export audit records"
        footer={<>
          <Button variant="secondary" onClick={() => setConfirmExport(false)}>Cancel</Button>
          <Button busy={exporting} onClick={doExport}>Export {data?.total.toLocaleString()} records</Button>
        </>}>
        <p>Export the <b>{data?.total.toLocaleString()}</b> records that match the current filters as JSON, in chain order with their hashes.</p>
        <p className="mt-2 text-muted">The export itself is recorded in the audit trail.</p>
      </Dialog>
    </div>
  )
}
