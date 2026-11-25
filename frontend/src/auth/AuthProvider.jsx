/**
 * Who is signed in (PROJECT_SPEC §18.2, design brief §5.1–5.2).
 *
 * The access token is kept in memory only. After a page reload the HttpOnly refresh cookie
 * restores the session (POST /auth/refresh). `lastRefreshAt` drives the idle-timeout warning:
 * the server ends a session 30 min after the refresh token was last used (§13.1).
 */
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react'
import { api, configureAuth, refreshSession } from '../api/client'

const AuthContext = createContext(null)

export function AuthProvider({ children }) {
  const token = useRef(null)
  const [user, setUser] = useState(null)
  const [status, setStatus] = useState('loading') // loading | signed_in | signed_out
  const [lastRefreshAt, setLastRefreshAt] = useState(null)

  const acceptTokens = useCallback((data) => {
    token.current = data.access_token
    setLastRefreshAt(Date.now())
  }, [])

  const signedOut = useCallback(() => {
    token.current = null
    setUser(null)
    setStatus('signed_out')
  }, [])

  useEffect(() => {
    configureAuth({ getToken: () => token.current, setToken: acceptTokens,
      onSessionLost: signedOut })
  }, [acceptTokens, signedOut])

  const loadMe = useCallback(async () => {
    const me = await api('/api/me')
    setUser(me)
    setStatus('signed_in')
    return me
  }, [])

  // restore the session from the refresh cookie (page reload)
  useEffect(() => {
    let cancelled = false
    ;(async () => {
      const renewed = await refreshSession()
      if (cancelled) return
      if (!renewed) return signedOut()
      try {
        await loadMe()
      } catch {
        if (!cancelled) signedOut()
      }
    })()
    return () => { cancelled = true }
  }, [loadMe, signedOut])

  const login = useCallback(async (username, password) => {
    const data = await api('/api/auth/login', { method: 'POST', body: { username, password },
      auth: false })
    acceptTokens(data)
    return loadMe()
  }, [acceptTokens, loadMe])

  const logout = useCallback(async () => {
    try {
      await api('/api/auth/logout', { method: 'POST', auth: false })
    } finally {
      signedOut()
    }
  }, [signedOut])

  const changePassword = useCallback(async (currentPassword, newPassword) => {
    const data = await api('/api/auth/change-password', { method: 'POST',
      body: { current_password: currentPassword, new_password: newPassword } })
    acceptTokens(data) // the server revoked the other sessions and issued a new one
    return loadMe()
  }, [acceptTokens, loadMe])

  const stayActive = useCallback(async () => {
    const renewed = await refreshSession()
    if (!renewed) signedOut()
  }, [signedOut])

  const value = useMemo(() => ({ user, status, lastRefreshAt, login, logout, changePassword,
    stayActive, reloadUser: loadMe }),
  [user, status, lastRefreshAt, login, logout, changePassword, stayActive, loadMe])
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth() outside <AuthProvider>')
  return ctx
}
