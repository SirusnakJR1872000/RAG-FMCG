// The API client's silent refresh (PROJECT_SPEC §18.2): one refresh and one retry on 401.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError, api, configureAuth, query } from './client'

const json = (status, body) => new Response(body === undefined ? null : JSON.stringify(body), {
  status, headers: { 'Content-Type': 'application/json' } })
const unauthorized = () => json(401, { error: { code: 'TOKEN_EXPIRED', message: 'expired',
  request_id: 'req_1' } })

let token
let lost
let calls

function serve(handler) {
  calls = []
  vi.stubGlobal('fetch', vi.fn(async (path, init) => {
    calls.push({ path, auth: init.headers?.Authorization ?? null, method: init.method })
    return handler(path, init, calls.length)
  }))
}

beforeEach(() => {
  token = 'old'
  lost = 0
  configureAuth({
    getToken: () => token,
    setToken: (data) => { token = data.access_token },
    onSessionLost: () => { lost += 1 },
  })
})
afterEach(() => vi.unstubAllGlobals())

describe('api()', () => {
  it('sends the bearer token and returns the JSON body', async () => {
    serve(() => json(200, { ok: true }))
    expect(await api('/api/me')).toEqual({ ok: true })
    expect(calls[0].auth).toBe('Bearer old')
  })

  it('on 401 refreshes once, then retries the request with the new token', async () => {
    serve((path, init) => {
      if (path === '/api/auth/refresh') return json(200, { access_token: 'new' })
      return init.headers.Authorization === 'Bearer new' ? json(200, { id: 'u_1' }) : unauthorized()
    })
    expect(await api('/api/me')).toEqual({ id: 'u_1' })
    expect(calls.map((c) => c.path)).toEqual(['/api/me', '/api/auth/refresh', '/api/me'])
    expect(token).toBe('new')
    expect(lost).toBe(0)
  })

  it('when the refresh fails, the session is lost and the 401 is thrown', async () => {
    serve((path) => (path === '/api/auth/refresh' ? json(401, { error: { code: 'INVALID_TOKEN' } })
      : unauthorized()))
    await expect(api('/api/me')).rejects.toMatchObject({ status: 401, code: 'TOKEN_EXPIRED' })
    expect(lost).toBe(1)
    expect(calls.filter((c) => c.path === '/api/auth/refresh')).toHaveLength(1)
  })

  it('a second 401 after a successful refresh does not loop: it gives up', async () => {
    serve((path) => (path === '/api/auth/refresh' ? json(200, { access_token: 'new' })
      : unauthorized()))
    await expect(api('/api/history')).rejects.toBeInstanceOf(ApiError)
    expect(calls).toHaveLength(3)
    expect(lost).toBe(1)
  })

  it('parallel 401s share ONE refresh (refresh tokens rotate; a second use is "reuse")',
    async () => {
      serve((path, init) => {
        if (path === '/api/auth/refresh') return json(200, { access_token: 'new' })
        return init.headers.Authorization === 'Bearer new' ? json(200, {}) : unauthorized()
      })
      await Promise.all([api('/api/me'), api('/api/history'), api('/api/documents')])
      expect(calls.filter((c) => c.path === '/api/auth/refresh')).toHaveLength(1)
    })

  it('turns the error envelope into an ApiError with the request id', async () => {
    serve(() => json(403, { error: { code: 'FORBIDDEN', message: 'Your role is not allowed.',
      request_id: 'req_abc' } }))
    await expect(api('/api/users')).rejects.toMatchObject({
      status: 403, code: 'FORBIDDEN', requestId: 'req_abc', message: 'Your role is not allowed.' })
  })

  it('a network failure becomes "Can\'t reach the server."', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => { throw new TypeError('Failed to fetch') }))
    await expect(api('/api/me')).rejects.toMatchObject({ code: 'NETWORK_ERROR',
      message: "Can't reach the server." })
  })

  it('calls made with auth: false never refresh', async () => {
    serve(() => json(401, { error: { code: 'INVALID_CREDENTIALS', message: 'no' } }))
    await expect(api('/api/auth/login', { method: 'POST', body: {}, auth: false }))
      .rejects.toMatchObject({ code: 'INVALID_CREDENTIALS' })
    expect(calls).toHaveLength(1)
    expect(calls[0].auth).toBeNull()
  })

  it('returns null for 204 No Content', async () => {
    serve(() => new Response(null, { status: 204 }))
    expect(await api('/api/auth/logout', { method: 'POST' })).toBeNull()
  })
})

describe('query()', () => {
  it('leaves out empty values and repeats array keys', () => {
    expect(query({ q: '', page: 2, event_type: ['A', 'B'], user: null })).toBe(
      '?page=2&event_type=A&event_type=B')
    expect(query({})).toBe('')
  })
})
