// A cited passage (design brief §5.3 Source card). Traceability is the hero: document, version,
// section, page and the passage itself, with a "Fictional" tag for Acme SOPs.
import { useEffect, useRef, useState } from 'react'
import { Badge, FictionalTag } from '../components/ui'

export default function SourceCard({ source, highlighted = false, superseded = null }) {
  const [expanded, setExpanded] = useState(false)
  const ref = useRef(null)
  useEffect(() => {
    if (highlighted) ref.current?.scrollIntoView?.({ behavior: 'smooth', block: 'nearest' })
  }, [highlighted])
  const long = (source.text ?? '').length > 320
  return (
    <article ref={ref} id={`source-${source.n}`} data-testid="source-card"
      className={`rounded-2xl border bg-surface p-4 transition-shadow ${
        highlighted ? 'border-primary ring-2 ring-primary-subtle' : 'border-line'}`}>
      <div className="flex items-start gap-2.5">
        <span className="rounded-md bg-primary-subtle px-1.5 py-0.5 text-xs font-semibold text-primary-ink">
          [{source.n}]
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="font-mono text-sm font-semibold">{source.doc_code}</span>
            {source.is_fictional && <FictionalTag />}
            {superseded && <Badge tone="warning">Superseded</Badge>}
          </div>
          {source.title && <p className="mt-0.5 text-sm text-muted">{source.title}</p>}
          <div className="mt-2 flex flex-wrap gap-1.5 text-xs">
            {source.section && (
              <span className="rounded-md bg-primary-subtle px-1.5 py-0.5 text-primary-ink">
                § {source.section}{source.section_title ? ` ${source.section_title}` : ''}
              </span>
            )}
            {source.page && <span className="rounded-md bg-info-bg px-1.5 py-0.5 text-info">p. {source.page}</span>}
            <span className="rounded-md bg-info-bg px-1.5 py-0.5 text-info">
              {/^\d/.test(source.version ?? '') ? `v${source.version}` : source.version}
            </span>
          </div>
          {superseded && (
            <p className="mt-2 text-xs text-warning-ink">Answered using version {source.version}; a newer version is now active.</p>
          )}
        </div>
      </div>
      {source.text && (
        <blockquote className="mt-3 rounded-xl bg-surface-muted p-3 text-sm leading-relaxed">
          <p className={expanded ? 'whitespace-pre-line' : 'line-clamp-5 whitespace-pre-line'}>{source.text}</p>
          {long && (
            <button type="button" onClick={() => setExpanded(!expanded)}
              className="mt-1 text-xs font-medium text-primary hover:underline">
              {expanded ? 'Show less' : 'Show more'}
            </button>
          )}
        </blockquote>
      )}
    </article>
  )
}
