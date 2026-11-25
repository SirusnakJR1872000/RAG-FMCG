// System health for admins (design brief §5.8), from GET /api/health/details.
import { useEffect, useState } from 'react'
import { useSystem } from '../auth/SystemStatus'
import { Card, CodeValue, Drawer, ErrorBlock, KeyValueList, Spinner } from '../components/ui'
import { localDateTime } from '../lib/format'

function Tile({ title, children }) {
  return (
    <Card className="p-5">
      <h3 className="mb-3 text-xs font-semibold uppercase tracking-widest text-muted">{title}</h3>
      {children}
    </Card>
  )
}

const yes = (ok, good = 'Yes', bad = 'No') => (
  <span className={ok ? 'text-success' : 'text-danger'}>{ok ? `✓ ${good}` : `✗ ${bad}`}</span>
)

export default function HealthDrawer({ open, onClose }) {
  const { loadDetails } = useSystem()
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  useEffect(() => {
    if (!open) return
    setError(null)
    loadDetails().then(setData).catch(setError)
  }, [open, loadDetails])
  return (
    <Drawer open={open} onClose={onClose} title="System health">
      <ErrorBlock error={error} />
      {!data && !error && <Spinner />}
      {data && (
        <div className="grid gap-4">
          <Tile title="AI model">
            <KeyValueList items={[['Ollama', yes(data.llm.reachable, 'Reachable', 'Unreachable')],
              ['Model', data.llm.model], ['In memory', yes(data.llm.loaded, 'Loaded', 'Not loaded')]]} />
          </Tile>
          <Tile title="Search index">
            {data.index.ready ? (
              <KeyValueList items={[
                ['Build', <CodeValue key="b" value={data.index.build_id} />],
                ['Built', localDateTime(data.index.built_at)],
                ['Passages', data.index.chunk_count?.toLocaleString()],
                ['Embedding model', data.index.embedding_model],
                ['Reranker', data.index.reranker_model]]} />
            ) : <p className="text-danger">Not ready: {data.index.error}</p>}
          </Tile>
          <Tile title="Documents">
            <p className="mb-2 text-sm">{data.documents.active_count} active</p>
            <ul className="max-h-40 space-y-0.5 overflow-y-auto text-xs text-muted">
              {data.documents.active_versions.map((d) => (
                <li key={d.doc_code}><span className="font-mono">{d.doc_code}</span> · {d.version}</li>
              ))}
            </ul>
          </Tile>
          <Tile title="Audit trail">
            <KeyValueList items={[['Last check', localDateTime(data.audit.verified_at)],
              ['Result', data.audit.ok ? yes(true, `Chain intact (${data.audit.checked} records)`)
                : yes(false, '', `Broken at record #${data.audit.first_bad_seq}`)]]} />
          </Tile>
          <Tile title="Storage and version">
            <KeyValueList items={[['Free disk', `${data.disk.free_gb} GB`],
              ['App version', data.version.app], ['Git commit', <CodeValue key="g" value={data.version.git_commit} />]]} />
          </Tile>
        </div>
      )}
    </Drawer>
  )
}
