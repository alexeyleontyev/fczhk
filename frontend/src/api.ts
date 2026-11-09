let token = ''
try {
  token = sessionStorage.getItem('fczhk-session') || ''
} catch {
  // Some embedded browsers disable storage; keep the session in memory instead.
}
let generation = 0
export const sessionVersion = () => generation
export function setToken(value: string) {
  if (token !== value) generation++
  token = value
  try {
    sessionStorage.setItem('fczhk-session', value)
  } catch {
    // Authentication still works for the lifetime of this page.
  }
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
export class ConnectionError extends ApiError {
  constructor(
    public uncertain: boolean,
    timeout: boolean,
  ) {
    super(
      uncertain
        ? 'Не удалось получить подтверждение сохранения. Изменения могли сохраниться. Проверьте актуальные данные перед повтором.'
        : timeout
          ? 'Сервер не ответил вовремя. Повторите попытку.'
          : 'Нет связи с сервером. Проверьте подключение и повторите попытку.',
      0,
    )
  }
}

// Bound the entire request, including the response body. Only reads are retried;
// an interrupted write may already have committed on the server.
async function request<T>(
  path: string,
  method: string,
  decode: (response: Response) => Promise<T>,
  body?: BodyInit,
  contentType = 'application/json',
): Promise<T> {
  const sentToken = token
  for (let attempt = 0; ; attempt++) {
    const controller = new AbortController()
    let timedOut = false
    let timer: ReturnType<typeof setTimeout> | undefined
    try {
      return await Promise.race([
        (async () => {
          const response = await fetch(`/api${path}`, {
            method,
            signal: controller.signal,
            headers: {
              'Content-Type': contentType,
              ...(sentToken ? { Authorization: `Bearer ${sentToken}` } : {}),
            },
            body,
          })
          if (!response.ok) {
            const data = await response.json().catch(() => ({}))
            const message =
              typeof data.detail === 'string'
                ? data.detail
                : Array.isArray(data.detail)
                  ? data.detail.map((e: { msg: string }) => e.msg).join('; ')
                  : 'Сервис временно недоступен. Повторите позже.'
            if (
              response.status === 401 &&
              sentToken &&
              sentToken === token &&
              !path.startsWith('/auth/')
            ) {
              setToken('')
              window.dispatchEvent(new Event(SESSION_EXPIRED))
            }
            throw new ApiError(message, response.status)
          }
          return decode(response)
        })(),
        new Promise<never>((_, reject) => {
          timer = setTimeout(
            () => {
              timedOut = true
              controller.abort()
              reject(new ConnectionError(method !== 'GET', true))
            },
            method === 'GET' ? 10000 : 15000,
          )
        }),
      ])
    } catch (cause) {
      const error =
        cause instanceof ApiError ? cause : new ConnectionError(method !== 'GET', timedOut)
      const retryable = error instanceof ConnectionError || [502, 503, 504].includes(error.status)
      if (method !== 'GET' || attempt > 0 || !retryable || sentToken !== token || !navigator.onLine)
        throw error
    } finally {
      clearTimeout(timer)
    }
    await new Promise((resolve) => setTimeout(resolve, 400))
  }
}

function changed(path: string, data: unknown) {
  window.dispatchEvent(new CustomEvent(DATA_CHANGED, { detail: { path, data } }))
}
async function json(response: Response): Promise<unknown> {
  if (response.status === 204) return null
  try {
    return await response.json()
  } catch {
    throw new ApiError(
      'Получен неполный ответ сервера. Обновите данные перед повтором действия.',
      502,
    )
  }
}
export async function api<T>(path: string, method = 'GET', body?: unknown): Promise<T> {
  const data = await request(
    path,
    method,
    json,
    body === undefined ? undefined : JSON.stringify(body),
  )
  if (method !== 'GET' && !path.startsWith('/auth/') && !path.endsWith('/lineup/preview'))
    changed(path, data)
  return data as T
}
export async function uploadImage(path: string, file: File): Promise<void> {
  changed(path, await request(path, 'PUT', json, file, file.type || 'application/octet-stream'))
}
export async function imageBlob(path: string): Promise<Blob> {
  return request(path, 'GET', (response) => response.blob())
}
