// User administration (design brief §5.7; PROJECT_SPEC §13, §16). The rules shown here (no
// change to your own account, at least one active admin) are also enforced by the backend.
import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../api/client'
import { useAuth } from '../auth/AuthProvider'
import Icon from '../components/Icon'
import { useToast } from '../components/Toasts'
import { Badge, Button, Card, CodeValue, Dialog, ErrorBlock, Field, INPUT, PageHeader,
  SkeletonRows, TD, TH } from '../components/ui'
import { localDate, localDateTime } from '../lib/format'
import { ROLE_DESCRIPTION, ROLE_LABEL } from '../lib/nav'

const ROLES = ['viewer', 'qa_user', 'auditor', 'admin']
export const USER_STATUS = {
  active: { tone: 'success', text: 'Active' },
  locked: { tone: 'danger', text: 'Locked' },
  deactivated: { tone: 'neutral', text: 'Deactivated' },
  must_change_password: { tone: 'warning', text: 'Must change password' },
}

/** Why an action is not allowed on this row, or null (mirrors the backend's rules). */
export function blockedReason(target, me, users, action) {
  if (action === 'unlock') return target.status === 'locked' ? null : 'The account is not locked.'
  if (target.status === 'deactivated') return 'The account is deactivated.'
  if (target.id === me.id) return 'You cannot change your own role or deactivate yourself.'
  const activeAdmins = users.filter((u) => u.role === 'admin' && u.status !== 'deactivated')
  if (target.role === 'admin' && activeAdmins.length <= 1) return 'There must be at least one active admin.'
  return null
}

function AddUser({ open, onClose, onCreated }) {
  const [form, setForm] = useState({ username: '', full_name: '', role: 'viewer' })
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [created, setCreated] = useState(null)
  useEffect(() => {
    if (open) { setForm({ username: '', full_name: '', role: 'viewer' }); setError(null); setCreated(null) }
  }, [open])
  async function submit(e) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const user = await api('/api/users', { method: 'POST', body: form })
      setCreated(user)
      onCreated()
    } catch (err) {
      setError(err.code === 'USERNAME_TAKEN'
        ? 'That username is already used (usernames are never reused, even after deactivation).'
        : err.code === 'VALIDATION_ERROR' ? 'Username: 3–32 characters, letters, digits, dot, dash or underscore.'
          : err.message)
    } finally {
      setBusy(false)
    }
  }
  if (created) {
    return (
      <Dialog open={open} onClose={onClose} title="User created"
        footer={<Button onClick={onClose}>Done</Button>}>
        <p><b>{created.username}</b> ({ROLE_LABEL[created.role]}) can now sign in with this temporary password:</p>
        <div className="my-3 rounded-xl border border-line bg-surface-muted p-3" data-testid="temporary-password">
          <CodeValue value={created.temporary_password} className="text-base" />
        </div>
        <p className="text-muted">It is shown only once. The user must change it at first sign-in.</p>
      </Dialog>
    )
  }
  return (
    <Dialog open={open} onClose={onClose} title="Add user">
      <form onSubmit={submit} className="space-y-4">
        <Field label="Username" htmlFor="new-username" hint="Lowercase letters, digits, dot, dash or underscore.">
          <input id="new-username" value={form.username} onChange={(e) => setForm({ ...form, username: e.target.value })}
            className={INPUT} autoFocus maxLength={32} />
        </Field>
        <Field label="Full name" htmlFor="new-fullname">
          <input id="new-fullname" value={form.full_name} onChange={(e) => setForm({ ...form, full_name: e.target.value })}
            className={INPUT} maxLength={100} />
        </Field>
        <fieldset className="space-y-2">
          <legend className="mb-1 text-sm font-medium">Role</legend>
          {ROLES.map((r) => (
            <label key={r} className={`flex cursor-pointer gap-3 rounded-xl border p-3 ${form.role === r ? 'border-primary bg-primary-subtle/40' : 'border-line'}`}>
              <input type="radio" name="role" value={r} checked={form.role === r} onChange={() => setForm({ ...form, role: r })} />
              <span><span className="block text-sm font-medium">{ROLE_LABEL[r]}</span>
                <span className="block text-xs text-muted">{ROLE_DESCRIPTION[r]}</span></span>
            </label>
          ))}
        </fieldset>
        {error && <p role="alert" className="rounded-lg bg-danger-bg p-3 text-sm text-danger">{error}</p>}
        <div className="flex justify-end gap-2">
          <Button variant="secondary" onClick={onClose}>Cancel</Button>
          <Button type="submit" busy={busy} disabled={form.username.trim().length < 3 || !form.full_name.trim()}>Create user</Button>
        </div>
      </form>
    </Dialog>
  )
}

function RowActions({ target, me, users, onAction }) {
  const [open, setOpen] = useState(false)
  const box = useRef(null)
  useEffect(() => {
    if (!open) return undefined
    const close = (e) => { if (!box.current?.contains(e.target)) setOpen(false) }
    document.addEventListener('mousedown', close)
    return () => document.removeEventListener('mousedown', close)
  }, [open])
  const item = (action, label, icon) => {
    const reason = blockedReason(target, me, users, action)
    return (
      <button type="button" role="menuitem" disabled={Boolean(reason)} title={reason ?? undefined}
        onClick={() => { setOpen(false); onAction(action, target) }}
        className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-sm hover:bg-surface-muted disabled:cursor-not-allowed disabled:text-slate-400 disabled:hover:bg-transparent">
        <Icon name={icon} /> {label}
      </button>
    )
  }
  return (
    <div className="relative" ref={box}>
      <button type="button" onClick={() => setOpen(!open)} aria-label={`Actions for ${target.username}`}
        aria-haspopup="menu" aria-expanded={open} className="rounded-lg p-1.5 text-muted hover:bg-surface-muted hover:text-ink">
        <Icon name="dots" size={18} />
      </button>
      {open && (
        <div role="menu" className="absolute right-0 z-20 mt-1 w-48 rounded-xl border border-line bg-surface p-1.5 shadow-lg">
          {item('role', 'Change role', 'users')}
          {item('unlock', 'Unlock', 'key')}
          {item('deactivate', 'Deactivate', 'x')}
        </div>
      )}
    </div>
  )
}

function ConfirmAction({ pending, onClose, onDone }) {
  const notify = useToast()
  const [role, setRole] = useState('viewer')
  const [busy, setBusy] = useState(false)
  useEffect(() => { if (pending?.action === 'role') setRole(pending.target.role) }, [pending])
  if (!pending) return null
  const { action, target } = pending
  async function confirm() {
    setBusy(true)
    const body = action === 'role' ? { role } : { [action]: true }
    try {
      await api(`/api/users/${target.id}`, { method: 'PATCH', body })
      notify({ role: `Role changed: ${ROLE_LABEL[target.role]} → ${ROLE_LABEL[role]}.`,
        unlock: `${target.username} unlocked.`, deactivate: `${target.username} deactivated.` }[action])
      onDone()
    } catch (err) {
      notify(err.message, 'error')
    } finally {
      setBusy(false)
    }
  }
  const title = { role: 'Change role', unlock: 'Unlock account', deactivate: 'Deactivate user' }[action]
  return (
    <Dialog open onClose={onClose} title={title}
      footer={<>
        <Button variant="secondary" onClick={onClose}>Cancel</Button>
        <Button variant={action === 'deactivate' ? 'danger' : 'primary'} busy={busy}
          disabled={action === 'role' && role === target.role} onClick={confirm}>{title}</Button>
      </>}>
      {action === 'role' && (
        <>
          <label htmlFor="role-select" className="mb-1 block">New role for <b>{target.username}</b></label>
          <select id="role-select" value={role} onChange={(e) => setRole(e.target.value)} className={INPUT}>
            {ROLES.map((r) => <option key={r} value={r}>{ROLE_LABEL[r]}</option>)}
          </select>
          <p className="mt-3 rounded-lg bg-surface-muted p-2 text-center">
            {ROLE_LABEL[target.role]} → <b>{ROLE_LABEL[role]}</b>
          </p>
          <p className="mt-2 text-muted">It takes effect on the user&apos;s next request.</p>
        </>
      )}
      {action === 'unlock' && <p>Allow <b>{target.username}</b> to sign in again now, and reset the failed-attempt count.</p>}
      {action === 'deactivate' && (
        <p><b>{target.username}</b> will be signed out everywhere and can no longer sign in. Users are never deleted:
          their records stay in the audit trail, and the username cannot be reused.</p>
      )}
    </Dialog>
  )
}

export default function Users() {
  const { user: me } = useAuth()
  const [users, setUsers] = useState(null)
  const [error, setError] = useState(null)
  const [adding, setAdding] = useState(false)
  const [pending, setPending] = useState(null)
  const load = useCallback(() => {
    setError(null)
    api('/api/users').then((d) => setUsers(d.items)).catch(setError)
  }, [])
  useEffect(load, [load])
  return (
    <div className="h-full overflow-y-auto px-4 py-8 lg:px-8">
      <div className="mx-auto max-w-6xl">
        <PageHeader label="Administration" title="Users" description="Accounts, roles and access."
          action={<Button onClick={() => setAdding(true)}><Icon name="plus" /> Add user</Button>} />
        <ErrorBlock error={error} onRetry={load} />
        <Card>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-surface-muted">
                <tr><th className={TH}>Username</th><th className={TH}>Full name</th><th className={TH}>Role</th>
                  <th className={TH}>Status</th><th className={TH}>Last sign-in</th><th className={TH}>Created</th>
                  <th className={TH}><span className="sr-only">Actions</span></th></tr>
              </thead>
              <tbody>
                {!users && !error && <SkeletonRows cols={7} />}
                {users?.map((u) => (
                  <tr key={u.id} className="border-t border-line" data-testid={`user-${u.username}`}>
                    <td className={`${TD} font-mono text-xs`}>{u.username}{u.id === me.id && <span className="ml-1 font-sans text-muted">(you)</span>}</td>
                    <td className={TD}>{u.full_name}</td>
                    <td className={TD}><Badge tone="primary">{ROLE_LABEL[u.role] ?? u.role}</Badge></td>
                    <td className={TD}><Badge tone={USER_STATUS[u.status]?.tone}>{USER_STATUS[u.status]?.text ?? u.status}</Badge></td>
                    <td className={`${TD} whitespace-nowrap text-muted`}>{u.last_login_at ? localDateTime(u.last_login_at) : 'Never'}</td>
                    <td className={`${TD} whitespace-nowrap text-muted`}>{localDate(u.created_at)}</td>
                    <td className={TD}><RowActions target={u} me={me} users={users} onAction={(action, target) => setPending({ action, target })} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      </div>
      <AddUser open={adding} onClose={() => setAdding(false)} onCreated={load} />
      <ConfirmAction pending={pending} onClose={() => setPending(null)} onDone={() => { setPending(null); load() }} />
    </div>
  )
}
