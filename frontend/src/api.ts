let token = sessionStorage.getItem('fczhk-session') || ''
export function setToken(value: string) {
  token = value
  sessionStorage.setItem('fczhk-session', value)
}
export function hasToken() {
  return Boolean(token)
}

export async function api<T>(path: string, method = 'GET', body?: unknown): Promise<T> {
  const response = await fetch(`/api${path}`, {
    method,
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  const data = await response.json()
  if (!response.ok) {
    const message =
      typeof data.detail === 'string'
        ? data.detail
        : Array.isArray(data.detail)
          ? data.detail.map((e: { msg: string }) => e.msg).join('; ')
          : 'Не удалось выполнить действие'
    throw new Error(message)
  }
  return data
}
