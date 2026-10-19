let token = sessionStorage.getItem('fczhk-session') || ''
export function setToken(value: string) {
  token = value
  sessionStorage.setItem('fczhk-session', value)
}
export function hasToken() {
  return Boolean(token)
}

export const SESSION_EXPIRED = 'fczhk-session-expired'
export const DATA_CHANGED = 'fczhk-data-changed'
export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message)
  }
}

export async function api<T>(path: string, method = 'GET', body?: unknown): Promise<T> {
  const sentToken = token
  const response = await fetch(`/api${path}`, {
    method,
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  const data = await response
    .json()
    .catch(() => ({ detail: 'Сервис временно недоступен. Повторите позже.' }))
  if (!response.ok) {
    const message =
      typeof data.detail === 'string'
        ? data.detail
        : Array.isArray(data.detail)
          ? data.detail.map((e: { msg: string }) => e.msg).join('; ')
          : 'Не удалось выполнить действие'
    if (response.status === 401 && sentToken && sentToken === token && !path.startsWith('/auth/')) {
      setToken('')
      window.dispatchEvent(new Event(SESSION_EXPIRED))
    }
    throw new ApiError(message, response.status)
  }
  if (method !== 'GET' && !path.startsWith('/auth/') && !path.endsWith('/lineup/preview'))
    window.dispatchEvent(new CustomEvent(DATA_CHANGED, { detail: { path, data } }))
  return data
}
