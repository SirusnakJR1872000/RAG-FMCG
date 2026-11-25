/**
 * fetch() wrapper for the backend API (PROJECT_SPEC §18.2).
 *
 * - The access token lives in memory only (AuthProvider), never in localStorage.
 * - A 401 triggers ONE silent refresh (the HttpOnly cookie) and one retry; if that fails too,
 *   the user is sent to /login.
 * - Concurrent 401s share a single refresh call: refresh tokens rotate, so two parallel refreshes
 *   would look like token theft to the server (reuse detection, §13.1).
 * - Errors become ApiError with the backend's {code, message, request_id}.
 */

export class ApiError extends Error {
  constructor(status, code, message, requestId = null, details = null) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.requestId = requestId
    this.details = details
  }
}

export const NETWORK_ERROR = 'NETWORK_ERROR'

const handlers = {
  getToken: () => null,
  setToken: () => {},
  onSessionLost: () => {},
}

/** Called by AuthProvider so this module can read and replace the in-memory token. */
export function configureAuth(next) {
  Object.assign(handlers, next)
}

async function toApiError(response) {
  let body = null
  try {
    body = await response.json()
  } catch {
    /* not JSON (e.g. a proxy error page) */
  }
  const e = body?.error ?? {}
  return new ApiError(response.status, e.code ?? `HTTP_${response.status}`,
    e.message ?? 'Something went wrong on the server.', e.request_id ?? null, e.details ?? null)
}

async function send(path, { method = 'GET', body, headers = {}, signal, token } = {}) {
  const init = { method, headers: { ...headers }, signal, credentials: 'same-origin' }
  if (token) init.headers.Authorization = `Bearer ${token}`
  if (body !== undefined) {
    init.headers['Content-Type'] = 'application/json'
    init.body = JSON.stringify(body)
  }
  try {
    return await fetch(path, init)
  } catch (err) {
    if (err?.name === 'AbortError') throw err
    throw new ApiError(0, NETWORK_ERROR, "Can't reach the server.")
  }
}

let refreshing = null

/** POST /api/auth/refresh once, however many callers ask at the same time. Returns the token
 *  response, or null if the session is gone. */
export function refreshSession() {
  if (!refreshing) {
    refreshing = (async () => {
      try {
        const response = await send('/api/auth/refresh', { method: 'POST' })
        if (!response.ok) return null
        const data = await response.json()
        handlers.setToken(data)
        return data
      } catch {
        return null
      } finally {
        refreshing = null // callers that already hold the promise still share its result
      }
    })()
  }
  return refreshing
}

/**
 * Call the API. Returns the parsed JSON body (null for 204), or the raw Response when
 * `raw: true` (streaming, downloads). Throws ApiError.
 */
export async function api(path, options = {}) {
  const { raw = false, auth = true, ...rest } = options
  let response = await send(path, { ...rest, token: auth ? handlers.getToken() : null })
  if (response.status === 401 && auth) {
    const renewed = await refreshSession()
    if (!renewed) {
      handlers.onSessionLost()
      throw await toApiError(response)
    }
    response = await send(path, { ...rest, token: renewed.access_token })
    if (response.status === 401) {
      handlers.onSessionLost()
      throw await toApiError(response)
    }
  }
  if (!response.ok) throw await toApiError(response)
  if (raw) return response
  if (response.status === 204) return null
  return response.json()
}

/** Build a query string, leaving out empty values; arrays become repeated keys. */
export function query(params) {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === '') continue
    if (Array.isArray(value)) value.forEach((v) => search.append(key, v))
    else search.append(key, String(value))
  }
  const text = search.toString()
  return text ? `?${text}` : ''
}
