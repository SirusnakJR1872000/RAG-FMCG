/**
 * System status for the top bar and the global banners (design brief §4.2–4.3).
 *
 * /api/health is public and says only ready | degraded | not_ready; it is polled every 30 s.
 * Admins also load /api/health/details (models, index, last audit verification). The audit
 * integrity result is shared here so the Audit page's "Verify now" updates the global banner.
 */
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import { api } from '../api/client'
import { can } from '../lib/nav'
import { useAuth } from './AuthProvider'

const POLL_MS = 30000
const SystemContext = createContext(null)

export function SystemStatusProvider({ children }) {
  const { user } = useAuth()
  const [health, setHealth] = useState('unknown')
  const [details, setDetails] = useState(null)
  const [integrity, setIntegrity] = useState(null) // {ok, checked, first_bad_seq, verified_at}

  const poll = useCallback(async () => {
    try {
      setHealth((await api('/api/health', { auth: false })).status)
    } catch {
      setHealth('unreachable')
    }
  }, [])

  const loadDetails = useCallback(async () => {
    const data = await api('/api/health/details')
    setDetails(data)
    if (data.audit?.ok !== undefined) setIntegrity(data.audit)
    return data
  }, [])

  useEffect(() => {
    if (!user) return undefined
    poll()
    const id = setInterval(poll, POLL_MS)
    return () => clearInterval(id)
  }, [user, poll])

  useEffect(() => {
    if (can(user, 'health:details')) loadDetails().catch(() => {})
    else setDetails(null)
  }, [user, loadDetails])

  const value = useMemo(() => ({ health, details, integrity, setIntegrity, loadDetails }),
    [health, details, integrity, loadDetails])
  return <SystemContext.Provider value={value}>{children}</SystemContext.Provider>
}

export const useSystem = () => useContext(SystemContext)

export const HEALTH_LABEL = {
  ready: { text: 'Ready', dot: 'bg-green-600', tip: 'All services are running.' },
  degraded: { text: 'Degraded', dot: 'bg-amber-500',
    tip: 'The AI model is offline or the audit check failed. Answers may not be available.' },
  not_ready: { text: 'Not ready', dot: 'bg-red-600', tip: 'The search index is not loaded.' },
  unreachable: { text: 'Offline', dot: 'bg-red-600', tip: "Can't reach the server." },
  unknown: { text: 'Checking…', dot: 'bg-slate-400', tip: 'Checking the system status.' },
}
