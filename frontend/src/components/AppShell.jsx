// Top bar, navigation filtered by role, user menu and global banners (design brief §4).
import { useEffect, useRef, useState } from 'react'
import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import { useAuth } from '../auth/AuthProvider'
import { HEALTH_LABEL, useSystem } from '../auth/SystemStatus'
import { can, navFor, ROLE_LABEL } from '../lib/nav'
import HealthDrawer from '../pages/HealthDrawer'
import Icon from './Icon'
import { Banner, Button } from './ui'

const IDLE_MINUTES = Number(import.meta.env.VITE_SESSION_IDLE_MINUTES ?? 30) // backend §13.1
const WARN_BEFORE_MS = 2 * 60 * 1000

function StatusPill() {
  const { health } = useSystem()
  const s = HEALTH_LABEL[health] ?? HEALTH_LABEL.unknown
  return (
    <span title={s.tip} data-testid="status-pill"
      className="hidden items-center gap-2 rounded-full border border-line bg-surface px-3 py-1 text-sm md:inline-flex">
      <span className={`h-2 w-2 rounded-full ${s.dot}`} aria-hidden />
      {s.text}
    </span>
  )
}

function UserMenu({ onHealth }) {
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  const [open, setOpen] = useState(false)
  const box = useRef(null)
  useEffect(() => {
    if (!open) return undefined
    const close = (e) => { if (!box.current?.contains(e.target)) setOpen(false) }
    const esc = (e) => e.key === 'Escape' && setOpen(false)
    document.addEventListener('mousedown', close)
    document.addEventListener('keydown', esc)
    return () => {
      document.removeEventListener('mousedown', close)
      document.removeEventListener('keydown', esc)
    }
  }, [open])
  const initials = user.full_name.split(/\s+/).map((w) => w[0]).slice(0, 2).join('').toUpperCase()
  const item = 'flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-sm hover:bg-surface-muted'
  return (
    <div className="relative" ref={box}>
      <button type="button" onClick={() => setOpen(!open)} aria-haspopup="menu" aria-expanded={open}
        className="flex items-center gap-2 rounded-xl px-2 py-1 hover:bg-surface-muted">
        <span className="grid h-8 w-8 place-items-center rounded-full bg-primary-subtle text-xs font-semibold text-primary-ink">
          {initials}
        </span>
        <span className="hidden text-left leading-tight lg:block">
          <span className="block text-sm font-medium">{user.full_name}</span>
          <span className="block text-xs text-muted">{ROLE_LABEL[user.role] ?? user.role}</span>
        </span>
        <Icon name="chevronDown" size={14} className="text-muted" />
      </button>
      {open && (
        <div role="menu" className="absolute right-0 z-30 mt-2 w-56 rounded-xl border border-line bg-surface p-1.5 shadow-lg">
          <div className="px-3 py-2 text-xs text-muted">Signed in as <b className="text-ink">{user.username}</b></div>
          <button type="button" role="menuitem" className={item}
            onClick={() => { setOpen(false); navigate('/change-password') }}>
            <Icon name="key" /> Change password
          </button>
          {can(user, 'health:details') && (
            <button type="button" role="menuitem" className={item}
              onClick={() => { setOpen(false); onHealth() }}>
              <Icon name="activity" /> System health
            </button>
          )}
          <button type="button" role="menuitem" className={item}
            onClick={async () => { setOpen(false); await logout(); navigate('/login') }}>
            <Icon name="logout" /> Sign out
          </button>
        </div>
      )}
    </div>
  )
}

function SessionWarning() {
  const { lastRefreshAt, stayActive } = useAuth()
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 15000)
    return () => clearInterval(id)
  }, [])
  if (!lastRefreshAt) return null
  const endsAt = lastRefreshAt + IDLE_MINUTES * 60000
  if (now < endsAt - WARN_BEFORE_MS) return null
  return (
    <Banner tone="neutral" icon="clock"
      action={<Button variant="secondary" onClick={stayActive}>Stay signed in</Button>}>
      Your session will end soon because of inactivity.
    </Banner>
  )
}

export default function AppShell() {
  const { user } = useAuth()
  const { health, integrity } = useSystem()
  const navigate = useNavigate()
  const [healthOpen, setHealthOpen] = useState(false)
  const showIntegrity = integrity && integrity.ok === false && can(user, 'audit:read')
  return (
    <div className="flex h-full flex-col">
      <header className="border-b border-line bg-surface">
        <div className="flex items-center gap-6 px-4 py-2.5 lg:px-6">
          <div className="flex items-center gap-2.5">
            <span className="grid h-9 w-9 place-items-center rounded-xl bg-primary-subtle text-primary">
              <Icon name="flask" size={20} />
            </span>
            <span className="leading-tight">
              <span className="block font-semibold">GMP Assistant</span>
              <span className="hidden text-xs text-muted sm:block">Quality Knowledge System</span>
            </span>
          </div>
          <nav aria-label="Main" className="flex flex-1 items-center gap-1 overflow-x-auto">
            {navFor(user).map((item) => (
              <NavLink key={item.to} to={item.to} end={item.to === '/'}
                className={({ isActive }) => `flex items-center gap-2 whitespace-nowrap rounded-full px-3.5 py-1.5 text-sm font-medium transition-colors ${
                  isActive ? 'bg-primary text-white' : 'text-muted hover:bg-surface-muted hover:text-ink'}`}>
                <Icon name={item.icon} size={16} />
                {item.label}
              </NavLink>
            ))}
          </nav>
          <StatusPill />
          <UserMenu onHealth={() => setHealthOpen(true)} />
        </div>
      </header>
      {showIntegrity && (
        <Banner tone="danger" icon="shield"
          action={<Button variant="secondary" onClick={() => navigate('/audit')}>View details</Button>}>
          Audit trail integrity check failed at record #{integrity.first_bad_seq}.
        </Banner>
      )}
      {health === 'degraded' && (
        <Banner tone="warning">The AI model is not available or the audit check failed. Questions may not be answered until it is fixed.</Banner>
      )}
      {(health === 'not_ready' || health === 'unreachable') && (
        <Banner tone="danger">
          {health === 'not_ready' ? 'The search index is not ready. Questions cannot be answered yet.'
            : "Can't reach the server. Check your connection."}
        </Banner>
      )}
      <SessionWarning />
      <main className="min-h-0 flex-1">
        <Outlet />
      </main>
      <HealthDrawer open={healthOpen} onClose={() => setHealthOpen(false)} />
    </div>
  )
}
