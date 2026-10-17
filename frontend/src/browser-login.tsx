import { useEffect, useRef, useState } from 'react'
import { api } from './api'
import type { TelegramLoginResult } from './types'

type Options = { browser_login: boolean; bot_url: string | null }
type Challenge = { client_id: number; nonce: string }

let sdk: Promise<void> | null = null
function loadSdk(): Promise<void> {
  if (window.Telegram?.Login) return Promise.resolve()
  if (sdk) return sdk
  sdk = new Promise<void>((resolve, reject) => {
    const script = document.createElement('script')
    script.src = 'https://telegram.org/js/telegram-login.js'
    script.async = true
    script.onload = () => {
      if (window.Telegram?.Login) resolve()
      else fail()
    }
    const timeout = window.setTimeout(fail, 15000)
    function fail() {
      window.clearTimeout(timeout)
      script.remove()
      sdk = null
      reject(
        new Error('Не удалось загрузить вход через Telegram. Проверьте соединение и повторите.'),
      )
    }
    script.onerror = fail
    script.addEventListener('load', () => window.clearTimeout(timeout))
    document.head.appendChild(script)
  })
  return sdk
}

export function BrowserLogin({ onLogin }: { onLogin: (token: string) => Promise<void> }) {
  const [options, setOptions] = useState<Options | null>(null)
  const [challenge, setChallenge] = useState<Challenge | null>(null)
  const [preparing, setPreparing] = useState(true)
  const [pending, setPending] = useState(false)
  const [error, setError] = useState('')
  const active = useRef(false)
  const attempt = useRef(0)

  async function prepare() {
    setPreparing(true)
    setChallenge(null)
    try {
      const config = await api<Options>('/auth/options')
      if (!active.current) return
      setOptions(config)
      if (config.browser_login) {
        await loadSdk()
        if (!active.current) return
        const next = await api<Challenge>('/auth/telegram/browser/challenge', 'POST')
        if (active.current) setChallenge(next)
      }
    } catch (e) {
      if (active.current) setError((e as Error).message)
    } finally {
      if (active.current) setPreparing(false)
    }
  }

  useEffect(() => {
    active.current = true
    // Defer setup so React StrictMode's discarded effect cannot issue a challenge.
    const timer = window.setTimeout(() => void prepare(), 0)
    return () => {
      active.current = false
      attempt.current += 1
      window.clearTimeout(timer)
      window.Telegram?.Login?.close()
    }
  }, [])

  function cancel() {
    attempt.current += 1
    window.Telegram?.Login?.close()
    setPending(false)
    setError('Вход отменён. Можно попробовать ещё раз.')
    void prepare()
  }

  function login() {
    const telegram = window.Telegram?.Login
    if (!challenge || !telegram || pending) return
    setError('')
    setPending(true)
    const currentAttempt = ++attempt.current
    async function finish(result: TelegramLoginResult) {
      if (!active.current || currentAttempt !== attempt.current) return
      try {
        if (result.error || !result.id_token)
          throw new Error(
            result.error === 'popup_closed'
              ? 'Вход отменён. Можно попробовать ещё раз.'
              : 'Telegram не подтвердил вход. Попробуйте ещё раз.',
          )
        const data = await api<{ token: string }>('/auth/telegram/browser', 'POST', {
          id_token: result.id_token,
        })
        if (!active.current || currentAttempt !== attempt.current) return
        await onLogin(data.token)
      } catch (e) {
        if (active.current && currentAttempt === attempt.current) {
          setError((e as Error).message)
          await prepare()
        }
      } finally {
        if (active.current && currentAttempt === attempt.current) setPending(false)
      }
    }
    try {
      // Open directly in the click handler so browsers preserve the user gesture.
      telegram.auth(
        { ...challenge, scope: ['profile'], lang: 'ru' },
        (result) => void finish(result),
      )
    } catch {
      void finish({ error: 'unavailable' })
    }
  }

  return (
    <div className="welcome-actions">
      {error && (
        <div className="alert error" role="alert">
          {error}
        </div>
      )}
      {(preparing || options?.browser_login) && (
        <button className="button" onClick={login} disabled={!challenge || preparing || pending}>
          {preparing
            ? 'Готовим вход…'
            : pending
              ? 'Подтвердите вход в Telegram…'
              : 'Войти через Telegram'}
        </button>
      )}
      {pending && (
        <>
          <small>Если окно не открылось, разрешите всплывающие окна и повторите вход.</small>
          <button className="button secondary" onClick={cancel}>
            Отменить вход
          </button>
        </>
      )}
      {!preparing && !challenge && options?.browser_login !== false && (
        <button
          className="button secondary"
          onClick={() => {
            setError('')
            void prepare()
          }}
        >
          Повторить подключение
        </button>
      )}
      {options?.bot_url && (
        <a className="button secondary" href={options.bot_url}>
          Открыть Telegram-бота
        </a>
      )}
      <small>
        {options?.browser_login
          ? 'Доступ для участников нашего чата или канала. Пароль не нужен.'
          : 'Откройте Mini App через меню Telegram-бота вашего сообщества.'}
      </small>
    </div>
  )
}
