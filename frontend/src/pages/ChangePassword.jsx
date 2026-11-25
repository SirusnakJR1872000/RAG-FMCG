// Change password (design brief §5.2; rules from PROJECT_SPEC §13.2). Forced on first sign-in
// and after expiry: then there is no way to skip and no navigation.
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../auth/AuthProvider'
import Icon from '../components/Icon'
import { useToast } from '../components/Toasts'
import { Button, Card, Field, PasswordInput } from '../components/ui'
import { landingFor } from '../lib/nav'

const MIN_LENGTH = 12

export const RULE_TEXT = {
  TOO_SHORT: `At least ${MIN_LENGTH} characters`,
  TOO_LONG: 'At most 128 characters',
  COMMON: 'Not a common password',
  SAME_AS_USERNAME: 'Not your username',
  REUSED: 'Not one of your last 5 passwords',
}

export function liveRules(password, confirm) {
  return [
    { id: 'TOO_SHORT', ok: password.length >= MIN_LENGTH },
    { id: 'COMMON', ok: null }, // checked by the server on submit
    { id: 'REUSED', ok: null },
    { id: 'MATCH', ok: password.length > 0 && password === confirm },
  ]
}

function Rule({ text, ok, failed }) {
  const state = failed ? false : ok
  return (
    <li className={`flex items-center gap-2 text-sm ${state === true ? 'text-success'
      : state === false ? 'text-danger' : 'text-muted'}`}>
      <Icon name={state === true ? 'check' : state === false ? 'x' : 'info'} size={14} />
      {text}{state === null && <span className="text-xs">(checked when you submit)</span>}
    </li>
  )
}

export default function ChangePassword() {
  const { user, changePassword } = useAuth()
  const notify = useToast()
  const navigate = useNavigate()
  const forced = user.must_change_password
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const [confirm, setConfirm] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [serverFailed, setServerFailed] = useState([])

  const rules = liveRules(next, confirm)
  const ready = current && rules.every((r) => r.ok !== false)

  async function submit(e) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    setServerFailed([])
    try {
      const me = await changePassword(current, next)
      notify('Password changed.')
      navigate(landingFor(me), { replace: true })
    } catch (err) {
      if (err.code === 'PASSWORD_POLICY') {
        setServerFailed((err.details ?? []).map((d) => d.rule))
        setError('The new password does not meet the rules below.')
      } else if (err.code === 'WRONG_CURRENT_PASSWORD') setError('The current password is incorrect.')
      else setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  const extra = serverFailed.filter((r) => !['TOO_SHORT', 'COMMON', 'REUSED'].includes(r))
  return (
    <div className="grid min-h-full place-items-center p-4">
      <Card className="w-full max-w-md p-6">
        <h1 className="text-xl font-bold">{forced ? 'Choose a new password' : 'Change password'}</h1>
        {forced && (
          <p className="mt-2 text-sm text-muted">
            You are using a temporary or expired password. Choose a new one to continue.
          </p>
        )}
        <form onSubmit={submit} className="mt-5 space-y-4" noValidate>
          <Field label="Current password" htmlFor="current">
            <PasswordInput id="current" value={current} onChange={setCurrent} autoComplete="current-password" />
          </Field>
          <Field label="New password" htmlFor="new">
            <PasswordInput id="new" value={next} onChange={setNext} autoComplete="new-password" />
          </Field>
          <Field label="Confirm new password" htmlFor="confirm">
            <PasswordInput id="confirm" value={confirm} onChange={setConfirm} autoComplete="new-password" />
          </Field>
          <ul className="space-y-1" aria-label="Password rules">
            {rules.map((r) => (
              <Rule key={r.id} text={r.id === 'MATCH' ? 'Both entries match' : RULE_TEXT[r.id]}
                ok={r.ok} failed={serverFailed.includes(r.id)} />
            ))}
            {extra.map((r) => <Rule key={r} text={RULE_TEXT[r] ?? r} ok={false} failed />)}
          </ul>
          {error && <p role="alert" className="rounded-lg bg-danger-bg p-3 text-sm text-danger">{error}</p>}
          <div className="flex justify-end gap-2">
            {!forced && <Button variant="secondary" onClick={() => navigate(-1)}>Cancel</Button>}
            <Button type="submit" busy={busy} disabled={!ready}>Change password</Button>
          </div>
        </form>
      </Card>
    </div>
  )
}
