// Sign in (design brief §5.1). Unknown user, wrong password and deactivated account all get the
// same message on purpose: the form must not reveal which accounts exist.
import { useState } from 'react'
import { Link, Navigate, useNavigate } from 'react-router-dom'
import { useAuth } from '../auth/AuthProvider'
import Icon from '../components/Icon'
import { Button, Card, Field, INPUT, PasswordInput } from '../components/ui'
import { landingFor } from '../lib/nav'

export function loginMessage(error) {
  if (error.code === 'ACCOUNT_LOCKED') {
    return 'Account locked after too many attempts. Try again in 30 minutes or contact your administrator.'
  }
  if (error.code === 'RATE_LIMITED') return 'Too many attempts. Wait a minute and try again.'
  if (error.code === 'NETWORK_ERROR') return "Can't reach the server."
  if (error.status === 401 || error.status === 422) return 'Username or password is incorrect.'
  return error.message
}

export default function Login() {
  const { user, login } = useAuth()
  const navigate = useNavigate()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  if (user) return <Navigate to={user.must_change_password ? '/change-password' : landingFor(user)} replace />

  async function submit(e) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const me = await login(username, password)
      navigate(me.must_change_password ? '/change-password' : landingFor(me), { replace: true })
    } catch (err) {
      setError(loginMessage(err))
      setPassword('')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="grid min-h-full place-items-center p-4">
      <div className="w-full max-w-sm">
        <div className="mb-6 flex items-center gap-3">
          <span className="grid h-11 w-11 place-items-center rounded-xl bg-primary-subtle text-primary">
            <Icon name="flask" size={24} />
          </span>
          <div>
            <h1 className="text-xl font-bold">GMP Assistant</h1>
            <p className="text-sm text-muted">Cited answers from controlled GMP documents and SOPs.</p>
          </div>
        </div>
        <Card className="p-6">
          <form onSubmit={submit} className="space-y-4" noValidate>
            <Field label="Username" htmlFor="username">
              <input id="username" autoComplete="username" value={username} disabled={busy}
                onChange={(e) => setUsername(e.target.value)} className={INPUT} autoFocus />
            </Field>
            <Field label="Password" htmlFor="password">
              <PasswordInput id="password" value={password} onChange={setPassword} disabled={busy}
                autoComplete="current-password" />
            </Field>
            {error && (
              <p role="alert" className="flex items-start gap-2 rounded-lg bg-danger-bg p-3 text-sm text-danger">
                <Icon name="alert" className="mt-0.5 shrink-0" /> {error}
              </p>
            )}
            <Button type="submit" busy={busy} className="w-full" disabled={!username || !password}>
              Sign in
            </Button>
          </form>
        </Card>
        <p className="mt-4 text-center text-xs text-muted">Authorised users only. All activity is recorded.</p>
        <p className="mt-2 text-center text-xs"><Link to="/welcome" className="text-primary hover:underline">About GMP Assistant</Link></p>
      </div>
    </div>
  )
}
