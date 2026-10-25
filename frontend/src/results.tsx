import { SectionTabs } from './section-tabs'
import { useEffect, useState } from 'react'
import { api } from './api'
import { SeasonSelect, seasonQuery, type SeasonFilter } from './seasons'
import { percentTone } from './percent'
import { TelegramIdentity } from './telegram-identity'
import { PlayerName } from './player-name'
import { RatingAverages } from './ratings'
import { PlayerReviews } from './player-reviews'
import type { Match, Player, Position, Run, Team, TelegramProfile } from './types'

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
  assist_team_switches?: { goal_id: string; player_id: number; team: Team }[]
}
const teams: Team[] = ['white', 'black']
const label = (team: Team) => (team === 'white' ? '⚪ Белые' : '⚫ Чёрные')

export function MatchResult({
  match: m,
  players,
  admin,
  busy,
  run,
  initialEditing = false,
  onDone,
}: {
  match: Match
  players: Player[]
  admin: boolean
  busy: boolean
  run: Run
  initialEditing?: boolean
  onDone?: () => void
}) {
  const [data, setData] = useState<Result | null>(null)
  const [editing, setEditing] = useState(initialEditing)
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
  const name = (id: number | null) => (
    <PlayerName
      playerId={id}
      alias={data?.participants.find((p) => p.player_id === id)?.alias || 'Автор неизвестен'}
    />
  )
  function applyScore(white: number, black: number) {
    if (!data) return
    if (white + black > 200) {
      setError('Всего допускается не более 200 голов.')
      return
    }
    const goals: Goal[] = []
    for (const team of teams) {
      const target = team === 'white' ? white : black
      const current = data.goals.filter((goal) => goal.team === team)
      const filled = current.filter(
        (goal) => goal.kind === 'own_goal' || goal.author_id !== null || goal.assist_id !== null,
      )
      if (target < filled.length) {
        setError(
          `У команды «${team === 'white' ? 'Белые' : 'Чёрные'}» уже заполнены ${filled.length} голов. Сначала исправьте или удалите лишние события.`,
        )
        return
      }
      const keep = new Set(filled.map((goal) => goal.id))
      for (const goal of current) if (keep.size < target) keep.add(goal.id)
      goals.push(...current.filter((goal) => keep.has(goal.id)))
      for (let i = current.length; i < target; i++)
        goals.push({
          id: crypto.randomUUID(),
          team,
          kind: 'goal',
          author_id: null,
          assist_id: null,
        })
    }
    setData({ ...data, goals })
    setError('')
  }
  const save = async (completed: boolean) => {
    let success = false
    await run(
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
        success = true
      },
      completed ? 'Результат сохранён. Статистика обновлена.' : 'Черновик результата сохранён',
    )
    if (success) onDone?.()
  }
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
              <details className="compact-explanation">
                <summary>Фактические составы</summary>
                <div className="actual-teams">
                  {teams.map((team) => (
                    <div key={team}>
                      <h3>{label(team)}</h3>
                      {data.participants
                        .filter((p) => p.team === team)
                        .map((p) => (
                          <p key={p.player_id}>
                            {p.position === 'keeper' ? '🧤 ' : ''}
                            <PlayerName playerId={p.player_id} alias={p.alias} />
                          </p>
                        ))}
                    </div>
                  ))}
                </div>
              </details>
              <h3>Голы и передачи</h3>
              {!data.goals.length && <p className="muted">Без голов</p>}
              {data.goals.map((g) => (
                <p key={g.id}>
                  {label(g.team)} · {name(g.author_id)}
                  {g.kind === 'own_goal' ? ' — автогол' : ''}
                  {g.assist_id && <> · передача: {name(g.assist_id)}</>}
                  {data.assist_team_switches?.some(
                    (s) => s.goal_id === g.id && s.player_id === g.assist_id,
                  )
                    ? ' (играл за обе команды)'
                    : ''}
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
              <details className="compact-explanation">
                <summary>Участники и замены · {data.participants.length}</summary>
                <h3>Кто фактически играл</h3>
                <p className="muted caption">
                  Уберите неявившихся, добавьте замены и проверьте команды. Участника с голами или
                  передачами можно убрать после исправления этих событий.
                </p>
                {data.participants.map((p) => (
                  <div className="actual-row" key={p.player_id}>
                    <strong>
                      <PlayerName playerId={p.player_id} alias={p.alias} />
                    </strong>
                    <label>
                      Команда
                      <select
                        aria-label={`Фактическая команда: ${p.alias}`}
                        value={p.team}
                        onChange={(e) =>
                          updatePerson(p.player_id, { team: e.target.value as Team })
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
                          participants: data.participants.filter(
                            (x) => x.player_id !== p.player_id,
                          ),
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
                            {
                              player_id: p.id,
                              alias: p.alias,
                              team: 'white',
                              position: p.shared_keeper ? 'keeper' : 'field',
                            },
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
              </details>
              <h3>События матча</h3>
              <form
                className="quick-score"
                aria-label="Быстрый ввод счёта"
                key={`${score('white')}:${score('black')}`}
                onSubmit={(event) => {
                  event.preventDefault()
                  const values = new FormData(event.currentTarget)
                  applyScore(Number(values.get('white')), Number(values.get('black')))
                }}
              >
                <h4>Быстрый ввод счёта</h4>
                <div className="prediction-inputs">
                  <label>
                    Счёт белых
                    <input
                      name="white"
                      type="number"
                      min={0}
                      max={200}
                      step={1}
                      required
                      defaultValue={score('white')}
                    />
                  </label>
                  <span>:</span>
                  <label>
                    Счёт чёрных
                    <input
                      name="black"
                      type="number"
                      min={0}
                      max={200}
                      step={1}
                      required
                      defaultValue={score('black')}
                    />
                  </label>
                </div>
                <button className="button secondary compact" type="submit">
                  Создать записи голов
                </button>
                <p className="muted caption">
                  Для каждого гола появится строка. Автора и передачу можно заполнить позже; уже
                  заполненные события сохраняются.
                </p>
              </form>
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
                  <label className="checkbox-label">
                    <input
                      type="checkbox"
                      checked={g.kind === 'own_goal'}
                      onChange={(e) =>
                        updateGoal(g.id, {
                          kind: e.target.checked ? 'own_goal' : 'goal',
                          author_id: null,
                          assist_id: null,
                        })
                      }
                    />
                    Автогол
                  </label>
                  {g.kind === 'own_goal' && (
                    <p className="muted caption">Автор автогола — игрок противоположной команды.</p>
                  )}
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
                      <option value="">Автор неизвестен</option>
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
                          .filter(
                            (p) =>
                              p.player_id !== g.author_id &&
                              (p.team === g.team ||
                                data.assist_team_switches?.some(
                                  (s) =>
                                    s.goal_id === g.id &&
                                    s.player_id === p.player_id &&
                                    s.team === g.team,
                                )),
                          )
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
                      onDone?.()
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

type Stats = TelegramProfile & {
  player_id: number
  alias: string
  games: number
  wins: number
  losses: number
  draws: number
  win_rate: number | null
  goals: number
  assists: number
  matches: {
    match_id: number
    starts_at: string
    team: Team
    score: Record<Team, number>
    goals: number
    assists: number
  }[]
  partners: {
    player_id: number
    alias: string
    games: number
    wins: number
    draws: number
    losses: number
    win_rate: number
  }[]
}
export function PlayerStats({
  playerId,
  player,
  showIdentity = true,
  onMatch,
  onPlayer,
  ...seasonFilter
}: SeasonFilter & {
  playerId: number
  player?: Player
  showIdentity?: boolean
  onMatch: (id: number) => void
  onPlayer: (id: number) => void
}) {
  const [data, setData] = useState<Stats | null>(null)
  const [error, setError] = useState('')
  const [section, setSection] = useState('overview')
  useEffect(() => {
    let current = true
    setData(null)
    setError('')
    api<Stats>(`/players/${playerId}/stats${seasonQuery(seasonFilter.season)}`)
      .then((x) => {
        if (current) setData(x)
      })
      .catch((e) => {
        if (current) setError(e.message)
      })
    return () => {
      current = false
    }
  }, [playerId, seasonFilter.season])
  const partnerRow = (p: Stats['partners'][number]) => (
    <button key={p.player_id} className="stat-link" onClick={() => onPlayer(p.player_id)}>
      <span>{p.alias}</span>
      <span className="partner-details">
        Игр: {p.games} · Винрейт:{' '}
        <span className={percentTone(p.win_rate)}>
          {p.win_rate.toLocaleString('ru-RU', { maximumFractionDigits: 1 })}%
        </span>{' '}
        <span className="partner-outcomes">
          ({p.wins}–{p.draws}–{p.losses})
        </span>
      </span>
    </button>
  )
  const matchRow = (m: Stats['matches'][number]) => (
    <button key={m.match_id} className="stat-link" onClick={() => onMatch(m.match_id)}>
      <span>
        {new Date(m.starts_at).toLocaleDateString('ru-RU', { timeZone: 'Europe/Moscow' })} ·{' '}
        {label(m.team)}
        {(m.goals > 0 || m.assists > 0) && (
          <span className="match-contributions">
            {m.goals > 0 && (
              <span title={`Голов: ${m.goals}`} aria-label={`Голов: ${m.goals}`}>
                <span aria-hidden="true">⚽</span> {m.goals}
              </span>
            )}
            {m.assists > 0 && (
              <span title={`Передач: ${m.assists}`} aria-label={`Передач: ${m.assists}`}>
                <span aria-hidden="true">👟</span> {m.assists}
              </span>
            )}
          </span>
        )}
      </span>
      <strong>
        {m.score.white} : {m.score.black} →
      </strong>
    </button>
  )
  return (
    <section className="statistics">
      <h2>{data ? `Статистика: ${data.alias}` : 'Статистика'}</h2>
      {data && showIdentity && <TelegramIdentity {...data} />}
      <SeasonSelect {...seasonFilter} />
      {error && (
        <p role="alert" className="alert error">
          {error}
        </p>
      )}
      {data && (
        <>
          <SectionTabs
            label="Статистика игрока"
            value={section}
            onChange={setSection}
            options={[
              { value: 'overview', label: 'Обзор' },
              { value: 'matches', label: 'Матчи' },
              { value: 'partners', label: 'Партнёры' },
            ]}
          >
            <div hidden={section !== 'overview'}>
              {' '}
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
                <div className="overall-win-rate-stat">
                  <strong
                    className={data.win_rate === null ? undefined : percentTone(data.win_rate)}
                  >
                    {data.win_rate === null
                      ? '—'
                      : `${data.win_rate.toLocaleString('ru-RU', { maximumFractionDigits: 1 })}%`}
                  </strong>
                  <span>Винрейт</span>
                </div>
              </div>
              {data.matches.length > 0 && (
                <div className="recent-form" aria-label="Результаты последних игр">
                  <span className="muted caption">Последние игры</span>
                  <div className="form-dots">
                    {data.matches
                      .slice(0, 5)
                      .reverse()
                      .map((match) => {
                        const other = match.team === 'white' ? 'black' : 'white'
                        const outcome =
                          match.score[match.team] > match.score[other]
                            ? 'win'
                            : match.score[match.team] === match.score[other]
                              ? 'draw'
                              : 'loss'
                        const title = `${new Date(match.starts_at).toLocaleDateString('ru-RU', { timeZone: 'Europe/Moscow' })}: ${outcome === 'win' ? 'Победа' : outcome === 'draw' ? 'Ничья' : 'Поражение'} · ${match.score.white} : ${match.score.black}`
                        return (
                          <button
                            type="button"
                            key={match.match_id}
                            className={`form-dot ${outcome}`}
                            aria-label={title}
                            title={title}
                            onClick={() => onMatch(match.match_id)}
                          />
                        )
                      })}
                  </div>
                </div>
              )}
              {player && !player.shared_keeper && (
                <div className="profile-ratings">
                  <h3>Оценки игрока</h3>
                  <RatingAverages player={player} />
                  <PlayerReviews key={playerId} playerId={playerId} />
                </div>
              )}
            </div>
            <div hidden={section !== 'matches'}>
              <h3>История игр</h3>
              {!data.matches.length && <p className="muted">Завершённых игр пока нет.</p>}
              {data.matches.slice(0, 5).map(matchRow)}
              {data.matches.length > 5 && (
                <details className="history-more" key={`${playerId}:${seasonFilter.season}`}>
                  <summary>Остальные игры ({data.matches.length - 5})</summary>
                  {data.matches.slice(5).map(matchRow)}
                </details>
              )}
            </div>
            <div hidden={section !== 'partners'}>
              <h3>Частые партнёры</h3>
              <p className="muted caption">В скобках: победы — ничьи — поражения.</p>
              {!data.partners.length && <p className="muted">Появятся после завершения матчей.</p>}
              {data.partners.slice(0, 3).map(partnerRow)}
              {data.partners.length > 3 && (
                <details className="partner-more" key={`${playerId}:${seasonFilter.season}`}>
                  <summary>Остальные партнёры ({data.partners.length - 3})</summary>
                  {data.partners.slice(3).map(partnerRow)}
                </details>
              )}
            </div>
          </SectionTabs>
        </>
      )}
    </section>
  )
}
