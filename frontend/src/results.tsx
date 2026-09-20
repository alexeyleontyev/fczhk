import { useEffect, useState } from 'react'
import { api } from './api'
import type { Match, Player, Position, Run, Team } from './types'

export type Participant = { player_id: number; alias: string; team: Team; position: Position }
export type Goal = {
  id: string
  team: Team
  kind: 'goal' | 'own_goal'
  author_id: number | null
  assist_id: number | null
}
export type Result = {
  exists: boolean
  completed: boolean
  version: number
  score: Record<Team, number>
  participants: Participant[]
  goals: Goal[]
}
const teams: Team[] = ['white', 'black']
const label = (team: Team) => (team === 'white' ? '⚪ Белые' : '⚫ Чёрные')

export function MatchResult({
  match: m,
  players,
  admin,
  busy,
  run,
}: {
  match: Match
  players: Player[]
  admin: boolean
  busy: boolean
  run: Run
}) {
  const [data, setData] = useState<Result | null>(null)
  const [editing, setEditing] = useState(false)
  const [error, setError] = useState('')
  useEffect(() => {
    let current = true
    api<Result>(`/matches/${m.id}/result`)
      .then((value) => {
        if (current) {
          setData(value)
          setError('')
        }
      })
      .catch((e) => {
        if (current) setError(e.message)
      })
    return () => {
      current = false
    }
  }, [m.id, m.version])
  const [clock, setClock] = useState(Date.now())
  useEffect(() => {
    const timer = setInterval(() => setClock(Date.now()), 1000)
    return () => clearInterval(timer)
  }, [])
  const updatePerson = (id: number, change: Partial<Participant>) =>
    setData(
      (d) =>
        d && {
          ...d,
          participants: d.participants.map((p) => (p.player_id === id ? { ...p, ...change } : p)),
        },
    )
  const updateGoal = (id: string, change: Partial<Goal>) =>
    setData(
      (d) => d && { ...d, goals: d.goals.map((g) => (g.id === id ? { ...g, ...change } : g)) },
    )
  const score = (team: Team) => data?.goals.filter((g) => g.team === team).length || 0
  const name = (id: number | null) =>
    data?.participants.find((p) => p.player_id === id)?.alias || 'Автор неизвестен'
  const save = (completed: boolean) =>
    run(
      async () => {
        if (!data) return
        const saved = await api<Result>(`/matches/${m.id}/result`, 'PUT', {
          version: data.version,
          completed,
          participants: data.participants.map(({ player_id, team, position }) => ({
            player_id,
            team,
            position,
          })),
          goals: data.goals,
        })
        setData(saved)
        setEditing(false)
      },
      completed ? 'Результат сохранён. Статистика обновлена.' : 'Черновик результата сохранён',
    )
  return (
    <section className="panel result-panel">
      <div className="section-title">
        <h2>Результат матча</h2>
        {data?.exists && <span className="tag">{data.completed ? 'Завершён' : 'Черновик'}</span>}
      </div>
      {error && (
        <p className="alert error" role="alert">
          {error}
        </p>
      )}
      {!data ? (
        <p>Загрузка результата…</p>
      ) : (
        <>
          {data.exists || editing ? (
            <div className="scoreboard" aria-label="Счёт матча">
              <span>{label('white')}</span>
              <strong>
                {score('white')} : {score('black')}
              </strong>
              <span>{label('black')}</span>
            </div>
          ) : (
            <p className="muted">Результат ещё не внесён.</p>
          )}
          {!editing && data.exists && (
            <>
              <div className="actual-teams">
                {teams.map((team) => (
                  <div key={team}>
                    <h3>{label(team)}</h3>
                    {data.participants
                      .filter((p) => p.team === team)
                      .map((p) => (
                        <p key={p.player_id}>
                          {p.position === 'keeper' ? '🧤 ' : ''}
                          {p.alias}
                        </p>
                      ))}
                  </div>
                ))}
              </div>
              <h3>Голы и передачи</h3>
              {!data.goals.length && <p className="muted">Без голов</p>}
              {data.goals.map((g) => (
                <p key={g.id}>
                  {label(g.team)} · {name(g.author_id)}
                  {g.kind === 'own_goal' ? ' — автогол в пользу соперника' : ''}
                  {g.assist_id ? ` · передача: ${name(g.assist_id)}` : ''}
                </p>
              ))}
            </>
          )}
          {admin && !editing && clock >= new Date(m.starts_at).getTime() && (
            <button className="button secondary" disabled={busy} onClick={() => setEditing(true)}>
              {data.exists ? 'Исправить результат' : 'Внести результат'}
            </button>
          )}
          {admin && !data.exists && clock < new Date(m.starts_at).getTime() && (
            <p className="muted caption">Ввод результата откроется после начала игры.</p>
          )}
          {editing && (
            <fieldset disabled={busy} className="result-editor">
              <h3>Кто фактически играл</h3>
              <p className="muted caption">
                Уберите неявившихся, добавьте замены и проверьте команды. Участника с голами или
                передачами можно убрать после исправления этих событий.
              </p>
              {data.participants.map((p) => (
                <div className="actual-row" key={p.player_id}>
                  <strong>{p.alias}</strong>
                  <label>
                    Команда
                    <select
                      aria-label={`Фактическая команда: ${p.alias}`}
                      value={p.team}
                      onChange={(e) => updatePerson(p.player_id, { team: e.target.value as Team })}
                    >
                      {teams.map((t) => (
                        <option key={t} value={t}>
                          {label(t)}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label>
                    Амплуа
                    <select
                      aria-label={`Фактическое амплуа: ${p.alias}`}
                      value={p.position}
                      onChange={(e) =>
                        updatePerson(p.player_id, { position: e.target.value as Position })
                      }
                    >
                      <option value="field">Полевой</option>
                      <option value="keeper">Вратарь</option>
                    </select>
                  </label>
                  <button
                    className="text-button danger"
                    disabled={data.goals.some(
                      (g) => g.author_id === p.player_id || g.assist_id === p.player_id,
                    )}
                    onClick={() =>
                      setData({
                        ...data,
                        participants: data.participants.filter((x) => x.player_id !== p.player_id),
                      })
                    }
                  >
                    Убрать {p.alias}
                  </button>
                </div>
              ))}
              <label>
                Добавить фактического участника
                <select
                  value=""
                  onChange={(e) => {
                    const p = players.find((x) => x.id === Number(e.target.value))
                    if (p)
                      setData({
                        ...data,
                        participants: [
                          ...data.participants,
                          { player_id: p.id, alias: p.alias, team: 'white', position: 'field' },
                        ],
                      })
                  }}
                >
                  <option value="">Выберите игрока</option>
                  {players
                    .filter((p) => !data.participants.some((x) => x.player_id === p.id))
                    .map((p) => (
                      <option key={p.id} value={p.id}>
                        {p.alias}
                        {p.guest ? ' · гость' : ''}
                      </option>
                    ))}
                </select>
              </label>
              <h3>События матча</h3>
              <p className="muted caption">
                Каждая строка добавляет один гол. Для неизвестного автора оставьте соответствующий
                пункт. Счёт вычисляется автоматически.
              </p>
              {data.goals.map((g, index) => (
                <div className="goal-editor" key={g.id}>
                  <strong>Гол {index + 1}</strong>
                  <label>
                    Засчитать команде
                    <select
                      value={g.team}
                      onChange={(e) =>
                        updateGoal(g.id, {
                          team: e.target.value as Team,
                          author_id: null,
                          assist_id: null,
                        })
                      }
                    >
                      {teams.map((t) => (
                        <option key={t} value={t}>
                          {label(t)}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label>
                    Тип гола
                    <select
                      value={g.kind}
                      onChange={(e) =>
                        updateGoal(g.id, {
                          kind: e.target.value as Goal['kind'],
                          author_id: null,
                          assist_id: null,
                        })
                      }
                    >
                      <option value="goal">Обычный гол</option>
                      <option value="own_goal">Автогол</option>
                    </select>
                  </label>
                  <label>
                    Автор гола
                    <select
                      value={g.author_id || ''}
                      onChange={(e) =>
                        updateGoal(g.id, {
                          author_id: Number(e.target.value) || null,
                          assist_id: g.assist_id === Number(e.target.value) ? null : g.assist_id,
                        })
                      }
                    >
                      <option value="">
                        {g.kind === 'own_goal' ? 'Укажите автора автогола' : 'Автор неизвестен'}
                      </option>
                      {data.participants
                        .filter((p) =>
                          g.kind === 'own_goal' ? p.team !== g.team : p.team === g.team,
                        )
                        .map((p) => (
                          <option key={p.player_id} value={p.player_id}>
                            {p.alias}
                          </option>
                        ))}
                    </select>
                  </label>
                  {g.kind === 'goal' && (
                    <label>
                      Голевая передача
                      <select
                        value={g.assist_id || ''}
                        onChange={(e) =>
                          updateGoal(g.id, { assist_id: Number(e.target.value) || null })
                        }
                      >
                        <option value="">Без передачи / неизвестно</option>
                        {data.participants
                          .filter((p) => p.team === g.team && p.player_id !== g.author_id)
                          .map((p) => (
                            <option key={p.player_id} value={p.player_id}>
                              {p.alias}
                            </option>
                          ))}
                      </select>
                    </label>
                  )}
                  <button
                    className="text-button danger"
                    onClick={() =>
                      setData({ ...data, goals: data.goals.filter((x) => x.id !== g.id) })
                    }
                  >
                    Удалить гол {index + 1}
                  </button>
                </div>
              ))}
              <div className="inline wrap">
                {teams.map((t) => (
                  <button
                    key={t}
                    className="button secondary compact"
                    disabled={data.goals.length >= 200}
                    onClick={() =>
                      setData({
                        ...data,
                        goals: [
                          ...data.goals,
                          {
                            id: crypto.randomUUID(),
                            team: t,
                            kind: 'goal',
                            author_id: null,
                            assist_id: null,
                          },
                        ],
                      })
                    }
                  >
                    Гол: {label(t)}
                  </button>
                ))}
              </div>
              <div className="divider" />
              <div className="inline wrap">
                {!data.completed && (
                  <button className="button secondary" onClick={() => void save(false)}>
                    Сохранить черновик
                  </button>
                )}
                <button className="button" onClick={() => void save(true)}>
                  {data.completed ? 'Сохранить исправления' : 'Завершить матч'}
                </button>
                <button
                  className="button ghost"
                  onClick={() =>
                    void run(async () => {
                      setData(await api<Result>(`/matches/${m.id}/result`))
                      setEditing(false)
                    })
                  }
                >
                  Отменить изменения
                </button>
              </div>
            </fieldset>
          )}
        </>
      )}
    </section>
  )
}

type Stats = {
  player_id: number
  alias: string
  games: number
  wins: number
  losses: number
  draws: number
  goals: number
  assists: number
  matches: { match_id: number; starts_at: string; team: Team; score: Record<Team, number> }[]
  partners: { player_id: number; alias: string; games: number }[]
}
export function PlayerStats({
  playerId,
  onMatch,
  onPlayer,
}: {
  playerId: number
  onMatch: (id: number) => void
  onPlayer: (id: number) => void
}) {
  const [data, setData] = useState<Stats | null>(null)
  const [error, setError] = useState('')
  useEffect(() => {
    let current = true
    setData(null)
    setError('')
    api<Stats>(`/players/${playerId}/stats`)
      .then((x) => {
        if (current) setData(x)
      })
      .catch((e) => {
        if (current) setError(e.message)
      })
    return () => {
      current = false
    }
  }, [playerId])
  return (
    <section className="statistics">
      <h2>{data ? `Статистика: ${data.alias}` : 'Статистика'}</h2>
      {error && (
        <p role="alert" className="alert error">
          {error}
        </p>
      )}
      {data && (
        <>
          <div className="stats-grid">
            {(
              [
                ['games', 'Игры'],
                ['wins', 'Победы'],
                ['draws', 'Ничьи'],
                ['losses', 'Поражения'],
                ['goals', 'Голы'],
                ['assists', 'Передачи'],
              ] as const
            ).map(([key, title]) => (
              <div key={key}>
                <strong>{data[key]}</strong>
                <span>{title}</span>
              </div>
            ))}
          </div>
          <h3>Частые партнёры</h3>
          {!data.partners.length && <p className="muted">Появятся после завершения матчей.</p>}
          {data.partners.map((p) => (
            <button key={p.player_id} className="stat-link" onClick={() => onPlayer(p.player_id)}>
              <span>{p.alias}</span>
              <span>{p.games} совместных игр</span>
            </button>
          ))}
          <h3>История игр</h3>
          {!data.matches.length && <p className="muted">Завершённых игр пока нет.</p>}
          {data.matches.map((m) => (
            <button key={m.match_id} className="stat-link" onClick={() => onMatch(m.match_id)}>
              <span>
                {new Date(m.starts_at).toLocaleDateString('ru-RU', { timeZone: 'Europe/Moscow' })} ·{' '}
                {label(m.team)}
              </span>
              <strong>
                {m.score.white} : {m.score.black} →
              </strong>
            </button>
          ))}
        </>
      )}
    </section>
  )
}
