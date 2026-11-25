// Small shared components (design brief §6). Styling uses the theme tokens only.
import { useEffect, useRef, useState } from 'react'
import Icon from './Icon'

const BUTTON = {
  primary: 'bg-primary text-white hover:bg-primary-hover disabled:bg-blue-300',
  secondary: 'bg-surface text-ink border border-line hover:bg-surface-muted disabled:text-muted',
  ghost: 'text-ink hover:bg-surface-muted disabled:text-muted',
  danger: 'bg-red-600 text-white hover:bg-red-700 disabled:bg-red-300',
}

export function Button({ variant = 'primary', className = '', busy = false, children, ...rest }) {
  return (
    <button type="button" {...rest} disabled={rest.disabled || busy}
      className={`inline-flex items-center justify-center gap-2 rounded-xl px-4 py-2 text-sm font-medium transition-colors disabled:cursor-not-allowed ${BUTTON[variant]} ${className}`}>
      {busy && <Spinner className="h-4 w-4" />}
      {children}
    </button>
  )
}

export function Spinner({ className = 'h-5 w-5' }) {
  return (
    <svg className={`animate-spin ${className}`} viewBox="0 0 24 24" fill="none" aria-hidden>
      <circle cx="12" cy="12" r="9" stroke="currentColor" strokeOpacity="0.25" strokeWidth="3" />
      <path d="M21 12a9 9 0 0 0-9-9" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
    </svg>
  )
}

const TONES = {
  neutral: 'bg-info-bg text-info',
  primary: 'bg-primary-subtle text-primary-ink',
  success: 'bg-success-bg text-success',
  warning: 'bg-warning-bg text-warning-ink',
  danger: 'bg-danger-bg text-danger',
  fictional: 'bg-fictional-bg text-fictional',
}

export function Badge({ tone = 'neutral', children, className = '', title }) {
  return (
    <span title={title}
      className={`inline-flex items-center gap-1 whitespace-nowrap rounded-full px-2.5 py-0.5 text-xs font-medium ${TONES[tone]} ${className}`}>
      {children}
    </span>
  )
}

export function FictionalTag() {
  return <Badge tone="fictional" title="Acme Pharma Ltd. is a fictional company">Fictional</Badge>
}

export function Card({ className = '', children, ...rest }) {
  return (
    <div {...rest} className={`rounded-2xl border border-line bg-surface shadow-sm ${className}`}>
      {children}
    </div>
  )
}

export function PageHeader({ label, title, description, action }) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div>
        <div className="text-xs font-semibold uppercase tracking-widest text-muted">{label}</div>
        <h1 className="mt-1 text-3xl font-bold tracking-tight">{title}</h1>
        {description && <p className="mt-1 text-muted">{description}</p>}
      </div>
      {action}
    </div>
  )
}

export function Banner({ tone = 'warning', icon = 'alert', children, action }) {
  const tones = {
    warning: 'border-amber-200 bg-warning-bg text-warning-ink',
    danger: 'border-red-200 bg-danger-bg text-danger',
    neutral: 'border-line bg-surface text-ink',
  }
  return (
    <div role={tone === 'danger' ? 'alert' : 'status'}
      className={`flex items-center gap-3 border-b px-6 py-2.5 text-sm ${tones[tone]}`}>
      <Icon name={icon} size={18} />
      <div className="flex-1">{children}</div>
      {action}
    </div>
  )
}

/** Monospace value with a copy button (hashes, ids). */
export function CodeValue({ value, display, className = '' }) {
  const [copied, setCopied] = useState(false)
  async function copy() {
    try {
      await navigator.clipboard.writeText(value)
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    } catch {
      /* clipboard blocked: the value stays selectable */
    }
  }
  return (
    <span className={`inline-flex max-w-full items-center gap-1.5 ${className}`}>
      <code className="truncate font-mono text-xs" title={value}>{display ?? value}</code>
      {value && (
        <button type="button" onClick={copy} className="rounded p-0.5 text-muted hover:text-ink"
          aria-label="Copy" title={copied ? 'Copied' : 'Copy'}>
          <Icon name={copied ? 'check' : 'copy'} size={14} />
        </button>
      )}
    </span>
  )
}

export function KeyValueList({ items }) {
  return (
    <dl className="grid grid-cols-[minmax(110px,auto)_1fr] gap-x-4 gap-y-2 text-sm">
      {items.filter(Boolean).map(([key, value]) => (
        <div key={key} className="contents">
          <dt className="text-muted">{key}</dt>
          <dd className="min-w-0 break-words">{value ?? '—'}</dd>
        </div>
      ))}
    </dl>
  )
}

/** Right-side drawer; Esc closes it and focus moves into it (§9 accessibility). */
export function Drawer({ open, title, onClose, children, width = 'max-w-2xl' }) {
  const panel = useRef(null)
  useEffect(() => {
    if (!open) return undefined
    const onKey = (e) => e.key === 'Escape' && onClose()
    document.addEventListener('keydown', onKey)
    panel.current?.focus()
    return () => document.removeEventListener('keydown', onKey)
  }, [open, onClose])
  if (!open) return null
  return (
    <div className="fixed inset-0 z-40 flex justify-end">
      <div className="absolute inset-0 bg-slate-900/30" onClick={onClose} aria-hidden />
      <aside ref={panel} tabIndex={-1} role="dialog" aria-modal="true" aria-label={title}
        className={`relative flex h-full w-full ${width} flex-col bg-surface shadow-xl outline-none`}>
        <div className="flex items-center justify-between border-b border-line px-6 py-4">
          <h2 className="text-lg font-semibold">{title}</h2>
          <button type="button" onClick={onClose} className="rounded-lg p-1.5 text-muted hover:bg-surface-muted"
            aria-label="Close">
            <Icon name="x" size={18} />
          </button>
        </div>
        <div className="flex-1 overflow-y-auto px-6 py-5">{children}</div>
      </aside>
    </div>
  )
}

export function Dialog({ open, title, onClose, children, footer }) {
  useEffect(() => {
    if (!open) return undefined
    const onKey = (e) => e.key === 'Escape' && onClose()
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [open, onClose])
  if (!open) return null
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-slate-900/40" onClick={onClose} aria-hidden />
      <div role="dialog" aria-modal="true" aria-label={title}
        className="relative w-full max-w-md rounded-2xl bg-surface p-6 shadow-xl">
        <h2 className="text-lg font-semibold">{title}</h2>
        <div className="mt-3 text-sm">{children}</div>
        {footer && <div className="mt-6 flex justify-end gap-2">{footer}</div>}
      </div>
    </div>
  )
}

export function Field({ label, htmlFor, hint, error, children }) {
  return (
    <div className="space-y-1.5">
      <label htmlFor={htmlFor} className="block text-sm font-medium">{label}</label>
      {children}
      {hint && !error && <p className="text-xs text-muted">{hint}</p>}
      {error && <p className="text-xs text-danger" role="alert">{error}</p>}
    </div>
  )
}

export const INPUT_BASE = 'rounded-xl border border-line bg-surface px-3 py-2 text-sm outline-none focus:border-primary focus:ring-2 focus:ring-primary-subtle disabled:bg-surface-muted'
export const INPUT = `w-full ${INPUT_BASE}`

export function PasswordInput({ id, value, onChange, autoComplete, disabled }) {
  const [show, setShow] = useState(false)
  return (
    <div className="relative">
      <input id={id} type={show ? 'text' : 'password'} value={value} disabled={disabled}
        autoComplete={autoComplete} onChange={(e) => onChange(e.target.value)}
        className={`${INPUT} pr-10`} />
      <button type="button" onClick={() => setShow(!show)}
        className="absolute inset-y-0 right-0 px-3 text-muted hover:text-ink"
        aria-label={show ? 'Hide password' : 'Show password'}>
        <Icon name={show ? 'eyeOff' : 'eye'} size={16} />
      </button>
    </div>
  )
}

export function Pagination({ page, pageSize, total, onPage }) {
  const pages = Math.max(1, Math.ceil(total / pageSize))
  const first = total === 0 ? 0 : (page - 1) * pageSize + 1
  const last = Math.min(total, page * pageSize)
  return (
    <div className="flex items-center justify-between border-t border-line px-4 py-3 text-sm text-muted">
      <span>{first}–{last} of {total.toLocaleString()}</span>
      <div className="flex items-center gap-2">
        <Button variant="secondary" className="px-3 py-1" disabled={page <= 1}
          onClick={() => onPage(page - 1)}>Previous</Button>
        <span className="rounded-md bg-primary-subtle px-2.5 py-1 font-medium text-primary-ink">
          {page} / {pages}
        </span>
        <Button variant="secondary" className="px-3 py-1" disabled={page >= pages}
          onClick={() => onPage(page + 1)}>Next</Button>
      </div>
    </div>
  )
}

export function SkeletonRows({ rows = 6, cols = 5 }) {
  return Array.from({ length: rows }, (_, r) => (
    <tr key={r} className="border-t border-line">
      {Array.from({ length: cols }, (__, c) => (
        <td key={c} className="px-4 py-3"><div className="h-3.5 animate-pulse rounded bg-slate-200" /></td>
      ))}
    </tr>
  ))
}

export function ErrorBlock({ error, onRetry }) {
  if (!error) return null
  return (
    <div role="alert" className="flex items-start gap-3 rounded-xl border border-red-200 bg-danger-bg p-4 text-sm text-danger">
      <Icon name="alert" size={18} className="mt-0.5 shrink-0" />
      <div className="flex-1">
        <p>{error.message}</p>
        {error.requestId && <p className="mt-1 font-mono text-xs opacity-80">Reference: {error.requestId}</p>}
      </div>
      {onRetry && <Button variant="secondary" onClick={onRetry}>Try again</Button>}
    </div>
  )
}

export const TH = 'px-4 py-2.5 text-left text-xs font-semibold uppercase tracking-wide text-muted'
export const TD = 'px-4 py-3 align-top'
