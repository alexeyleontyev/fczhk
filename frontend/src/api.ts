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

async function request(
  path: string,
  method: string,
  body?: BodyInit,
  contentType = 'application/json',
): Promise<Response> {
  const sentToken = token
  const response = await fetch(`/api${path}`, {
    method,
    headers: {
      'Content-Type': contentType,
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body,
  })
  if (!response.ok) {
    const data = await response
      .json()
      .catch(() => ({ detail: 'Сервис временно недоступен. Повторите позже.' }))
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
  return response
}

function changed(path: string, data: unknown) {
  window.dispatchEvent(new CustomEvent(DATA_CHANGED, { detail: { path, data } }))
}

export async function api<T>(path: string, method = 'GET', body?: unknown): Promise<T> {
  const response = await request(
    path,
    method,
    body === undefined ? undefined : JSON.stringify(body),
  )
  const data = await response
    .json()
    .catch(() => ({ detail: 'Сервис временно недоступен. Повторите позже.' }))
  if (method !== 'GET' && !path.startsWith('/auth/') && !path.endsWith('/lineup/preview'))
    changed(path, data)
  return data
}

export async function uploadImage(path: string, file: File): Promise<void> {
  const response = await request(path, 'PUT', file, file.type || 'application/octet-stream')
  changed(path, await response.json())
}

export async function imageBlob(path: string): Promise<Blob> {
  return (await request(path, 'GET')).blob()
}
