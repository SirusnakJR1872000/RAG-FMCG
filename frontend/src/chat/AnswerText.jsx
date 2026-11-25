// Answer text with clickable [n] citation badges (PROJECT_SPEC §18.2). A number that matches no
// source is shown in amber, not as a link.
import { splitCitations } from './turns'

export default function AnswerText({ text, sources, onCite, streaming }) {
  const known = new Set(sources.map((s) => s.n))
  return (
    <div className={`whitespace-pre-line leading-relaxed ${streaming ? 'cursor-blink' : ''}`} data-testid="answer-text">
      {splitCitations(text).map((part, i) => {
        if (typeof part === 'string') return <span key={i}>{part}</span>
        const src = sources.find((s) => s.n === part.n)
        if (!known.has(part.n)) return <span key={i} className="text-warning-ink">[{part.n}]</span>
        return (
          <button key={i} type="button" onClick={() => onCite(part.n)}
            title={`${src.doc_code}${src.section ? ` § ${src.section}` : ''}`}
            className="mx-0.5 rounded-md bg-primary-subtle px-1.5 py-px align-baseline text-xs font-semibold text-primary-ink hover:bg-blue-200">
            [{part.n}]
          </button>
        )
      })}
    </div>
  )
}
