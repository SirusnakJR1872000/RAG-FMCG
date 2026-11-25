// Pure UI rules: menus by role, the conversation list, the Users page guards, login messages.
import { describe, expect, it } from 'vitest'
import { groupConversations } from '../chat/ConversationList'
import { loginMessage } from '../pages/Login'
import { blockedReason } from '../pages/Users'
import { landingFor, navFor } from './nav'

const PERMS = { // GET /api/me for each role (backend auth/permissions.py)
  viewer: ['docs:read', 'history:own', 'query:run'],
  qa_user: ['docs:manage', 'docs:read', 'history:own', 'query:run'],
  auditor: ['audit:export', 'audit:read', 'docs:read'],
  admin: ['audit:export', 'audit:read', 'docs:manage', 'docs:read', 'health:details',
    'history:own', 'query:run', 'users:manage'],
}
const as = (role) => ({ role, permissions: PERMS[role] })

describe('menus by role (design brief §3)', () => {
  it.each([
    ['viewer', ['Chat', 'History', 'Documents'], '/'],
    ['qa_user', ['Chat', 'History', 'Documents'], '/'],
    ['auditor', ['Documents', 'Audit'], '/audit'],
    ['admin', ['Chat', 'History', 'Documents', 'Audit', 'Users'], '/'],
  ])('%s sees %j and lands on %s', (role, labels, landing) => {
    expect(navFor(as(role)).map((n) => n.label)).toEqual(labels)
    expect(landingFor(as(role))).toBe(landing)
  })
})

describe('groupConversations', () => {
  it('titles each conversation by its FIRST question and orders by latest activity', () => {
    const items = [ // newest first, as /api/history returns them
      { conversation_id: 'c2', question: 'Follow-up on PQR', timestamp_utc: '2026-11-25T10:05:00Z' },
      { conversation_id: 'c1', question: 'Second OOS question', timestamp_utc: '2026-11-25T09:10:00Z' },
      { conversation_id: 'c2', question: 'How often is a PQR needed?', timestamp_utc: '2026-11-25T10:00:00Z' },
      { conversation_id: 'c1', question: 'What is an OOS result?', timestamp_utc: '2026-11-25T09:00:00Z' },
      { conversation_id: null, question: 'From a script', timestamp_utc: '2026-11-25T11:00:00Z' },
    ]
    expect(groupConversations(items).map((c) => [c.id, c.title])).toEqual([
      ['c2', 'How often is a PQR needed?'], ['c1', 'What is an OOS result?']])
  })
})

describe('Users page guards (mirror the backend)', () => {
  const me = { id: 'u_me', role: 'admin', status: 'active' }
  const other = { id: 'u_2', role: 'admin', status: 'active' }
  const viewer = { id: 'u_3', role: 'viewer', status: 'locked' }
  it('an admin cannot change or deactivate their own account, but the rest is allowed', () => {
    expect(blockedReason(me, me, [me, other], 'role')).toMatch(/own role/)
    expect(blockedReason(me, me, [me, other], 'deactivate')).toMatch(/own role/)
    expect(blockedReason(other, me, [me, other], 'deactivate')).toBeNull()
  })
  it('the last active admin cannot be removed', () => {
    const gone = { ...other, status: 'deactivated' }
    expect(blockedReason({ ...me, id: 'x' }, { id: 'y' }, [{ ...me, id: 'x' }, gone], 'role'))
      .toMatch(/at least one active admin/)
  })
  it('unlock is offered only for a locked account', () => {
    expect(blockedReason(viewer, me, [me, viewer], 'unlock')).toBeNull()
    expect(blockedReason(other, me, [me, other], 'unlock')).toMatch(/not locked/)
  })
})

describe('loginMessage (design brief §5.1)', () => {
  it('never reveals whether the account exists or is deactivated', () => {
    expect(loginMessage({ status: 401, code: 'INVALID_CREDENTIALS' }))
      .toBe('Username or password is incorrect.')
    expect(loginMessage({ status: 423, code: 'ACCOUNT_LOCKED' })).toMatch(/locked after too many/)
    expect(loginMessage({ status: 429, code: 'RATE_LIMITED' })).toMatch(/Wait a minute/)
    expect(loginMessage({ status: 0, code: 'NETWORK_ERROR' })).toBe("Can't reach the server.")
  })
})
