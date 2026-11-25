// Display helpers. Records are stored in UTC; the UI shows local time (§9).

export function localDateTime(iso) {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleString(undefined, { year: 'numeric', month: 'short', day: '2-digit',
    hour: '2-digit', minute: '2-digit' })
}

export function localDate(iso) {
  if (!iso) return '—'
  const d = new Date(iso.length === 10 ? `${iso}T00:00:00` : iso)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: '2-digit' })
}

export function seconds(ms) {
  if (ms === null || ms === undefined) return '—'
  return ms < 10000 ? `${(ms / 1000).toFixed(1)} s` : `${Math.round(ms / 1000)} s`
}

export function shortHash(hash, n = 10) {
  return hash ? `${hash.slice(0, n)}…${hash.slice(-4)}` : '—'
}

/** Today / Yesterday / Earlier, for the conversation list. */
export function dayGroup(iso, now = new Date()) {
  const d = new Date(iso)
  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate())
  if (d >= startOfToday) return 'Today'
  if (d >= new Date(startOfToday.getTime() - 86400000)) return 'Yesterday'
  return 'Earlier'
}

export function truncate(text, n) {
  if (!text) return ''
  return text.length > n ? `${text.slice(0, n - 1).trimEnd()}…` : text
}
