// Documents: which documents and versions the assistant answers from (design brief §5.5).
// Read-only in Tier 1; the header keeps a free slot for Tier 2's "Upload document".
import { useEffect, useMemo, useState } from 'react'
import { api } from '../api/client'
import { useAuth } from '../auth/AuthProvider'
import { useSystem } from '../auth/SystemStatus'
import Icon from '../components/Icon'
import { Badge, Card, CodeValue, Drawer, ErrorBlock, FictionalTag, INPUT, INPUT_BASE, KeyValueList,
  PageHeader, SkeletonRows, TD, TH } from '../components/ui'
import { can } from '../lib/nav'
import { localDate } from '../lib/format'

export const STATUS = {
  active: { tone: 'success', text: 'Active' },
  superseded: { tone: 'warning', text: 'Superseded' },
  withdrawn: { tone: 'danger', text: 'Withdrawn' },
}

function Stat({ icon, label, value, sub }) {
  return (
    <Card className="flex items-center gap-4 p-5">
      <span className="grid h-11 w-11 place-items-center rounded-xl bg-primary-subtle text-primary"><Icon name={icon} size={20} /></span>
      <div className="min-w-0">
        <div className="text-xs font-medium text-muted">{label}</div>
        <div className="truncate text-2xl font-bold" title={typeof value === 'string' ? value : undefined}>{value}</div>
        {sub && <div className="truncate text-xs text-muted">{sub}</div>}
      </div>
    </Card>
  )
}

function DocIcon({ fictional }) {
  return (
    <span className={`grid h-8 w-8 shrink-0 place-items-center rounded-lg ${fictional ? 'bg-fictional-bg text-fictional' : 'bg-info-bg text-info'}`}>
      <Icon name="documents" />
    </span>
  )
}

function Detail({ doc, all, onClose }) {
  const versions = doc ? all.filter((d) => d.doc_code === doc.doc_code)
    .sort((a, b) => (a.ingested_at < b.ingested_at ? 1 : -1)) : []
  return (
    <Drawer open={Boolean(doc)} onClose={onClose} title={doc?.doc_code ?? ''}>
      {doc && (
        <div className="space-y-6">
          {doc.is_fictional && (
            <p className="rounded-xl bg-fictional-bg p-3 text-sm text-fictional">
              Fictional document: Acme Pharma Ltd. is an invented company, used to demonstrate internal SOPs.
            </p>
          )}
          <KeyValueList items={[
            ['Title', doc.title],
            ['Document code', <span key="c" className="font-mono">{doc.doc_code}</span>],
            ['Version', doc.version],
            ['Status', <Badge key="s" tone={STATUS[doc.status].tone}>{STATUS[doc.status].text}</Badge>],
            doc.status_reason ? ['Reason', doc.status_reason] : null,
            ['Effective date', localDate(doc.effective_date)],
            ['Publisher', doc.publisher],
            ['Passages', doc.chunk_count],
            ['Pages', doc.page_count ?? '—'],
            ['Ingested', localDate(doc.ingested_at)],
            ['SHA-256', <CodeValue key="h" value={doc.sha256} />],
          ]} />
          <section>
            <h3 className="mb-3 text-xs font-semibold uppercase tracking-widest text-muted">Version history</h3>
            <ol className="relative space-y-4 border-l border-line pl-5">
              {versions.map((v) => (
                <li key={v.id} className="relative">
                  <span className={`absolute -left-[26px] top-1 h-3 w-3 rounded-full border-2 border-surface ${
                    v.status === 'active' ? 'bg-green-600' : v.status === 'superseded' ? 'bg-amber-500' : 'bg-red-600'}`} />
                  <div className="flex items-center gap-2 text-sm">
                    <span className="font-medium">Version {v.version}</span>
                    <Badge tone={STATUS[v.status].tone}>{STATUS[v.status].text}</Badge>
                  </div>
                  <p className="text-xs text-muted">Effective {localDate(v.effective_date)} · ingested {localDate(v.ingested_at)}</p>
                </li>
              ))}
            </ol>
          </section>
        </div>
      )}
    </Drawer>
  )
}

export default function Documents() {
  const { user } = useAuth()
  const { details } = useSystem()
  const [docs, setDocs] = useState(null)
  const [error, setError] = useState(null)
  const [status, setStatus] = useState('active')
  const [kind, setKind] = useState('all')
  const [search, setSearch] = useState('')
  const [open, setOpen] = useState(null)

  function load() {
    setError(null)
    api('/api/documents').then((d) => setDocs(d.items)).catch(setError)
  }
  useEffect(load, [])

  const rows = useMemo(() => {
    const needle = search.trim().toLowerCase()
    return (docs ?? []).filter((d) => (status === 'all' || d.status === status)
      && (kind === 'all' || (kind === 'sop') === d.is_fictional)
      && (!needle || `${d.doc_code} ${d.title} ${d.publisher}`.toLowerCase().includes(needle)))
  }, [docs, status, kind, search])

  const active = (docs ?? []).filter((d) => d.status === 'active')
  const passages = active.reduce((sum, d) => sum + d.chunk_count, 0)
  const lastIngested = (docs ?? []).reduce((m, d) => (d.ingested_at > m ? d.ingested_at : m), '')
  const index = can(user, 'health:details') ? details?.index : null

  return (
    <div className="h-full overflow-y-auto px-4 py-8 lg:px-8">
      <div className="mx-auto max-w-6xl">
        <PageHeader label="Controlled knowledge base" title="Documents"
          description="The documents and versions the assistant answers from." />
        <div className="mb-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <Stat icon="documents" label="Active documents" value={docs ? active.length : '…'}
            sub={docs ? `${active.filter((d) => d.is_fictional).length} internal SOP(s)` : null} />
          <Stat icon="sources" label="Passages indexed" value={docs ? passages.toLocaleString() : '…'} sub="from active versions" />
          <Stat icon="clock" label={index ? 'Index built' : 'Last ingested'}
            value={index ? localDate(index.built_at) : (lastIngested ? localDate(lastIngested) : '…')} />
          {index && <Stat icon="activity" label="Embedding model" value={index.embedding_model?.split('/').pop()} sub={index.embedding_model} />}
        </div>
        <div className="mb-4 flex flex-wrap items-center gap-3">
          <label className="relative min-w-60 flex-1">
            <span className="sr-only">Search documents</span>
            <Icon name="search" className="absolute left-3 top-1/2 -translate-y-1/2 text-muted" />
            <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search code, title or publisher…"
              className={`${INPUT} pl-9`} />
          </label>
          <select value={status} onChange={(e) => setStatus(e.target.value)} className={`${INPUT_BASE} w-auto`} aria-label="Status">
            <option value="active">Active</option><option value="superseded">Superseded</option>
            <option value="withdrawn">Withdrawn</option><option value="all">All statuses</option>
          </select>
          <select value={kind} onChange={(e) => setKind(e.target.value)} className={`${INPUT_BASE} w-auto`} aria-label="Type">
            <option value="all">All types</option><option value="public">Public guidance</option>
            <option value="sop">Internal SOP</option>
          </select>
          <span className="text-sm text-muted">{rows.length} shown</span>
        </div>
        <ErrorBlock error={error} onRetry={load} />
        <Card className="overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-surface-muted">
                <tr>
                  <th className={TH}>Document</th><th className={TH}>Version</th><th className={TH}>Effective</th>
                  <th className={TH}>Publisher</th><th className={TH}>Status</th><th className={TH}>Passages</th>
                  <th className={TH}>Ingested</th>
                </tr>
              </thead>
              <tbody>
                {!docs && !error && <SkeletonRows cols={7} />}
                {rows.map((d) => (
                  <tr key={d.id} onClick={() => setOpen(d)} tabIndex={0} onKeyDown={(e) => e.key === 'Enter' && setOpen(d)}
                    className="cursor-pointer border-t border-line hover:bg-surface-muted">
                    <td className={TD}>
                      <div className="flex items-start gap-3">
                        <DocIcon fictional={d.is_fictional} />
                        <div className="min-w-0">
                          <div className="flex items-center gap-1.5">
                            <span className="font-mono text-xs font-semibold">{d.doc_code}</span>
                            {d.is_fictional && <FictionalTag />}
                          </div>
                          <div className="text-muted">{d.title}</div>
                        </div>
                      </div>
                    </td>
                    <td className={TD}>{d.version}</td>
                    <td className={`${TD} whitespace-nowrap`}>{localDate(d.effective_date)}</td>
                    <td className={TD}>{d.publisher}</td>
                    <td className={TD}><Badge tone={STATUS[d.status].tone}>{STATUS[d.status].text}</Badge></td>
                    <td className={TD}>{d.chunk_count}</td>
                    <td className={`${TD} whitespace-nowrap text-muted`}>{localDate(d.ingested_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {docs && rows.length === 0 && <p className="p-10 text-center text-muted">No documents match these filters.</p>}
        </Card>
      </div>
      <Detail doc={open} all={docs ?? []} onClose={() => setOpen(null)} />
    </div>
  )
}
