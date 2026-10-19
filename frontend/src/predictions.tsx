import { useEffect, useState } from 'react'
import { api } from './api'
import { SeasonSelect, seasonQuery, type SeasonFilter } from './seasons'
import type { Match, Run } from './types'

type Forecast = {
  player_id: number
  alias: string
  white_score: number
  black_score: number
  revision: number
  approved_version: number
  points: number | null
  teams_changed: boolean
}
type PredictionData = {
  server_time: string
  deadline: string
  available: boolean
  closed: boolean
  approved_version: number | null
  count: number
  mine: Forecast | null
  forecasts: Forecast[]
  actual: { white: number; black: number } | null
}
const rules =
  '3 очка — победитель и разница мячей; 1 очко — только победитель или ничья. Иначе — 0. Очки не складываются.'

export function PredictionPanel({
  match: m,
  busy,
  run,
  onStandings,
}: {
  match: Match
  busy: boolean
  run: Run
  onStandings: () => void
}) {
  const [data, setData] = useState<PredictionData | null>(null)
  const [error, setError] = useState('')
  const [time, setTime] = useState({ server: 0, received: 0 })
  const [tick, setTick] = useState(performance.now())
  const accept = (value: PredictionData) => {
    setData(value)
    setTime({ server: new Date(value.server_time).getTime(), received: performance.now() })
    setTick(performance.now())
    setError('')
  }
  useEffect(() => {
    let current = true
    api<PredictionData>(`/matches/${m.id}/predictions`)
      .then((value) => {
        if (current) accept(value)
      })
      .catch((e) => {
        if (current) setError(e.message)
      })
    return () => {
      current = false
    }
  }, [m.id, m.version])
  useEffect(() => {
    const timer = setInterval(() => setTick(performance.now()), 1000)
    return () => clearInterval(timer)
  }, [])
  const remaining = data
    ? new Date(data.deadline).getTime() - (time.server + tick - time.received)
    : 0
  const expired = Boolean(data && remaining <= 0)
  useEffect(() => {
    if (!expired || !data || data.closed) return
    let current = true
    api<PredictionData>(`/matches/${m.id}/predictions`)
      .then((value) => {
        if (current) accept(value)
      })
      .catch((e) => {
        if (current) setError(e.message)
      })
    return () => {
      current = false
    }
  }, [expired, data?.closed, m.id])
  const editable = data?.available && !expired
  const reload = () =>
    run(async () => accept(await api<PredictionData>(`/matches/${m.id}/predictions`)))
  return (
    <section className="panel prediction-panel">
      <div className="section-title">
        <h2>Прогноз на матч</h2>
        {data && <span className="tag">{data.count} прогнозов</span>}
      </div>
      <p className="muted caption">{rules}</p>
      {error && (
        <p className="alert error" role="alert">
          {error}
        </p>
      )}
      {!data && !error && <p>Загрузка прогнозов…</p>}
      {data && (
        <>
          <p>
            {data.closed || expired
              ? 'Приём прогнозов завершён'
              : data.available
                ? `До начала: ${Math.floor(remaining / 3600000)} ч ${Math.floor(remaining / 60000) % 60} мин ${Math.floor(remaining / 1000) % 60} с`
                : 'Прогнозы откроются после утверждения составов'}
          </p>
          <p className="muted caption">
            Начало:{' '}
            {new Date(data.deadline).toLocaleString('ru-RU', {
              timeZone: 'Europe/Moscow',
              dateStyle: 'short',
              timeStyle: 'short',
            })}{' '}
            МСК. Время проверяет сервер.
          </p>
          {data.mine && (
            <div className="prediction-own">
              <strong>
                Ваш прогноз: {data.mine.white_score} : {data.mine.black_score}
              </strong>
              <span>
                {data.mine.points === null
                  ? 'Ожидаем подтверждения результата'
                  : `Очки за матч: ${data.mine.points}`}
              </span>
            </div>
          )}
          {data.mine?.teams_changed && (
            <p className="alert">
              Составы или цвета команд изменились после вашего прогноза.{' '}
              {editable
                ? 'Проверьте команды и при необходимости обновите прогноз.'
                : 'Прогноз сохранён за белыми и чёрными.'}
            </p>
          )}
          {editable && (
            <form
              key={`${m.id}:${data.mine?.revision || 0}:${data.approved_version}`}
              onSubmit={(e) => {
                e.preventDefault()
                const f = new FormData(e.currentTarget)
                void run(async () => {
                  try {
                    accept(
                      await api<PredictionData>(`/matches/${m.id}/prediction`, 'PUT', {
                        white_score: Number(f.get('white')),
                        black_score: Number(f.get('black')),
                        revision: data.mine?.revision || 0,
                        approved_version: data.approved_version,
                      }),
                    )
                  } catch (error) {
                    accept(await api<PredictionData>(`/matches/${m.id}/predictions`))
                    throw error
                  }
                }, 'Прогноз сохранён')
              }}
            >
              <div className="prediction-inputs">
                <label>
                  Голы белых
                  <input
                    name="white"
                    type="number"
                    min={0}
                    max={200}
                    step={1}
                    required
                    defaultValue={data.mine?.white_score ?? 0}
                  />
                </label>
                <span>:</span>
                <label>
                  Голы чёрных
                  <input
                    name="black"
                    type="number"
                    min={0}
                    max={200}
                    step={1}
                    required
                    defaultValue={data.mine?.black_score ?? 0}
                  />
                </label>
              </div>
              <button className="button" disabled={busy}>
                {data.mine ? 'Изменить прогноз' : 'Сделать прогноз'}
              </button>
              <p className="muted caption">
                Можно менять до начала игры. Чужие прогнозы откроются после её начала.
              </p>
            </form>
          )}
          {data.closed && (
            <>
              {data.actual && (
                <p>
                  <strong>
                    Итог: белые {data.actual.white} : {data.actual.black} чёрные
                  </strong>
                </p>
              )}
              {!data.forecasts.length && <p className="muted">На эту игру прогнозов нет.</p>}
              {data.forecasts.map((p) => (
                <div className="forecast-row" key={p.player_id}>
                  <span>{p.alias}</span>
                  <strong>
                    {p.white_score} : {p.black_score}
                  </strong>
                  <span>{p.points === null ? '—' : `${p.points} очк.`}</span>
                </div>
              ))}
            </>
          )}
        </>
      )}
      <div className="inline wrap">
        <button className="button ghost compact" onClick={onStandings}>
          Общий зачёт прогнозов
        </button>
        <button className="button ghost compact" disabled={busy} onClick={() => void reload()}>
          Обновить прогнозы
        </button>
      </div>
    </section>
  )
}

type Standing = {
  rank: number
  player_id: number
  alias: string
  points: number
  three_points: number
  one_point: number
  settled: number
  predictions: number
}
export function PredictionStandings({
  me,
  onPlayer,
  ...seasonFilter
}: SeasonFilter & {
  me: number
  onPlayer: (id: number) => void
}) {
  const [data, setData] = useState<Standing[] | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [revision, setRevision] = useState(0)
  useEffect(() => {
    let active = true
    setLoading(true)
    setData(null)
    setError('')
    api<Standing[]>(`/predictions/standings${seasonQuery(seasonFilter.season)}`)
      .then((data) => {
        if (active) setData(data)
      })
      .catch((e) => {
        if (active) setError((e as Error).message)
      })
      .finally(() => {
        if (active) setLoading(false)
      })
    return () => {
      active = false
    }
  }, [seasonFilter.season, revision])
  return (
    <>
      <div className="page-heading">
        <div>
          <div className="eyebrow">КОНКУРС ПРОГНОЗОВ</div>
          <h1>{seasonFilter.season ? `Зачёт сезона ${seasonFilter.season}` : 'Общий зачёт'}</h1>
        </div>
        <button
          className="button secondary compact"
          disabled={loading}
          onClick={() => setRevision((value) => value + 1)}
        >
          Обновить зачёт
        </button>
      </div>
      <SeasonSelect {...seasonFilter} />
      <section className="panel standings-panel">
        <details className="compact-explanation">
          <summary>Правила конкурса</summary>
          <p className="muted">{rules}</p>
          <p className="muted caption">
            Учитываются только завершённые матчи. Исправления результата пересчитывают очки. При
            равенстве очков место общее.
          </p>
        </details>
        {error && (
          <p role="alert" className="alert error">
            {error}
          </p>
        )}
        {data?.length === 0 && (
          <p className="empty-small">
            Пока нет прогнозов. Сделайте первый после утверждения составов.
          </p>
        )}
        {data && data.length > 0 && (
          <table className="standings-table">
            <thead>
              <tr>
                <th>Место</th>
                <th>Прогнозист</th>
                <th>Очки</th>
              </tr>
            </thead>
            <tbody>
              {data.map((row) => (
                <tr key={row.player_id} className={row.player_id === me ? 'mine' : ''}>
                  <td>{row.rank}</td>
                  <td>
                    <button className="text-button" onClick={() => onPlayer(row.player_id)}>
                      {row.alias}
                      {row.player_id === me ? ' · вы' : ''}
                    </button>
                    <details className="prediction-row-details">
                      <summary>
                        Учтено {row.settled} из {row.predictions}
                      </summary>
                      <small>
                        Точный счёт: {row.three_points} · Исход: {row.one_point}
                      </small>
                    </details>
                  </td>
                  <td>
                    <strong>{row.points}</strong>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </>
  )
}
