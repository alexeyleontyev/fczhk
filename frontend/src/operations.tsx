import { useEffect, useState } from 'react'
import { api } from './api'
import { Button } from './ui'
import { date } from './format'
import type { Claim } from './profile-link'

type Problem = {
  id: number
  match_id: number
  game_day: string
  kind: string
  status: string
  stale: boolean
  error: string | null
  attempts: number
}
type Operations = {
  status: string
  worker: { healthy: boolean; age_seconds: number | null }
  queue_age_seconds: number
  errors: { http_5xx: number; webhook_errors: number }
  problems: Problem[]
}
export function OperationsPanel({ onMatch }: { onMatch: (id: number) => void }) {
  const [data, setData] = useState<Operations | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [revision, setRevision] = useState(0)
  useEffect(() => {
    let active = true
    const load = () =>
      api<Operations>('/operations')
        .then((value) => {
          if (active) {
            setData(value)
            setError('')
          }
        })
        .catch((e) => {
          if (active) setError(e.message)
        })
    void load()
    const timer = setInterval(() => void load(), 15000)
    return () => {
      active = false
      clearInterval(timer)
    }
  }, [revision])
  async function retry(problem: Problem) {
    if (
      problem.status === 'uncertain' &&
      !window.confirm(
        'Проверьте чат: сообщение могло быть отправлено. Повтор может создать дубликат. Отправить повторно?',
      )
    )
      return
    setBusy(true)
    try {
      await api(`/publications/${problem.id}/${problem.stale ? 'retry-stale' : 'retry'}`, 'POST')
      setRevision((x) => x + 1)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }
  return (
    <section className="panel">
      <h2>Доставка сообщений</h2>
      {error && (
        <p role="alert" className="alert error">
          {error}
        </p>
      )}
      {data && (
        <>
          <p>
            {data.worker.healthy
              ? 'Публикации обрабатываются'
              : 'Обработка публикаций остановлена или задерживается'}
            . Ожидание в очереди: {Math.round(data.queue_age_seconds)} с.
          </p>
          <details>
            <summary>Диагностика</summary>
            <p>
              Ошибки сервера с запуска: {data.errors.http_5xx}; входящих обновлений Telegram:{' '}
              {data.errors.webhook_errors}.
            </p>
          </details>
          {!data.problems.length && <p>Нет публикаций, требующих внимания.</p>}
          {data.problems.map((problem) => (
            <div className="publication" key={problem.id}>
              <button className="text-button" onClick={() => onMatch(problem.match_id)}>
                Игра {date(problem.game_day)}
              </button>
              <strong>
                {problem.kind === 'teams'
                  ? 'Составы'
                  : problem.kind === 'cancellation'
                    ? 'Отмена игры'
                    : problem.kind === 'auction_start'
                      ? 'Старт аукциона'
                      : problem.kind === 'result'
                        ? 'Итог игры'
                        : problem.kind === 'auction_lot'
                          ? 'Аукцион'
                          : 'Сбор'}{' '}
                ·{' '}
                {
                  (
                    {
                      pending: 'В очереди',
                      sending: 'Отправляется',
                      failed: 'Ошибка',
                      uncertain: 'Доставка не подтверждена',
                      sent: 'Нужна пометка старого поста',
                      demo: 'Демонстрация',
                    } as Record<string, string>
                  )[problem.status]
                }
              </strong>
              {problem.error && <p>{problem.error}</p>}
              {((problem.stale && ['sent', 'demo'].includes(problem.status)) ||
                (!problem.stale && ['failed', 'uncertain'].includes(problem.status))) && (
                <Button disabled={busy} className="secondary" onClick={() => void retry(problem)}>
                  {problem.stale ? 'Повторить пометку' : 'Повторить отправку'}
                </Button>
              )}
            </div>
          ))}
        </>
      )}
    </section>
  )
}

export function ScheduleExceptions() {
  const [days, setDays] = useState<{ game_day: string; reason: string }[]>([])
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const load = async () => setDays(await api('/schedule/skipped'))
  useEffect(() => {
    void load().catch((e) => setError(e.message))
  }, [])
  async function change(work: () => Promise<unknown>) {
    setBusy(true)
    setError('')
    try {
      await work()
      await load()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }
  return (
    <section className="panel form-panel">
      <h2>Пропустить неделю</h2>
      <p>
        В выбранную пятницу игра автоматически не создастся. Уже созданную игру отменяйте в её
        карточке.
      </p>
      {error && (
        <p role="alert" className="alert error">
          {error}
        </p>
      )}
      <form
        onSubmit={(e) => {
          e.preventDefault()
          const form = new FormData(e.currentTarget)
          void change(() =>
            api('/schedule/skipped', 'POST', {
              game_day: form.get('day'),
              reason: form.get('reason'),
            }),
          )
        }}
      >
        <label>
          Пятница
          <input name="day" type="date" required />
        </label>
        <label>
          Причина пропуска
          <input name="reason" required minLength={2} maxLength={300} />
        </label>
        <Button disabled={busy} type="submit">
          Пропустить неделю
        </Button>
      </form>
      {days.map((day) => (
        <div className="publication" key={day.game_day}>
          <span>
            {date(day.game_day)} · {day.reason}
          </span>
          <Button
            disabled={busy}
            className="ghost"
            onClick={() => {
              if (
                window.confirm(
                  'Вернуть эту неделю в расписание? Если период записи уже наступил, игра появится автоматически.',
                )
              )
                void change(() => api(`/schedule/skipped/${day.game_day}`, 'DELETE'))
            }}
          >
            Вернуть в расписание
          </Button>
        </div>
      ))}
    </section>
  )
}

export function ProfileClaims({ onResolved }: { onResolved: () => Promise<void> }) {
  const [claims, setClaims] = useState<Claim[]>([])
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const load = async () => setClaims(await api('/profile-claims'))
  useEffect(() => {
    void load().catch((e) => setError(e.message))
  }, [])
  async function resolve(claim: Claim, accept: boolean) {
    if (
      accept &&
      !window.confirm(
        `Подтверждаете, что «${claim.player}» и «${claim.guest}» — один человек? История будет объединена.`,
      )
    )
      return
    setBusy(true)
    try {
      await api(`/profile-claims/${claim.player_id}/resolve`, 'POST', {
        guest_id: claim.guest_id,
        accept,
      })
      await load()
      await onResolved()
      setError('')
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }
  return (
    <section className="panel">
      <h2>Привязка исторических карточек</h2>
      {error && (
        <p role="alert" className="alert error">
          {error}
        </p>
      )}
      {!claims.length && <p>Нет заявок на подтверждение.</p>}
      {claims.map((claim) => (
        <div className="publication" key={claim.player_id}>
          <p>
            {claim.player} → {claim.guest}
          </p>
          <div className="inline">
            <Button disabled={busy} onClick={() => void resolve(claim, true)}>
              Подтвердить связь
            </Button>
            <Button disabled={busy} className="ghost" onClick={() => void resolve(claim, false)}>
              Отклонить
            </Button>
          </div>
        </div>
      ))}
    </section>
  )
}
