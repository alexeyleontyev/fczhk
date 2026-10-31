import { useEffect, useState } from 'react'
import { CircleDot, Clock3, Hand, History as HistoryIcon, MapPin, Pencil, X } from 'lucide-react'
import { api } from './api'
import { time } from './format'
import { RatingMark, ratingNumber } from './rating-mark'
import { MatchHistory } from './match-history'
import { MatchResult, type Participant } from './results'
import { Button } from './ui'
import { PlayerName } from './player-name'
import type { Average, History, Match, Player, Position, Run, Team } from './types'

export const isArchivedMatch = (match: Match | null) =>
  Boolean(
    match && (match.status === 'completed' || match.status === 'cancelled' || match.historical),
  )
const unknownLocation = 'Не указано в историческом источнике'
type RatedPlayer = Average & { player_id: number; position: Position }
type Scores = { players: RatedPlayer[]; official_players: RatedPlayer[] | null }
const teamLabel = (team: Team) => (team === 'white' ? 'Белые' : 'Чёрные')

function total(players: (Average & { position: Position })[], withKeepers = false): string {
  const values = players
    .filter((p) => withKeepers || p.position === 'field')
    .flatMap((p) => (p.position === 'keeper' ? [p.defense] : [p.attack, p.defense]))
  const known = values.filter((value): value is number => value !== null)
  return known.length
    ? `${known.length < values.length ? '≥ ' : ''}${ratingNumber(known.reduce((sum, n) => sum + n, 0))}`
    : '—'
}

function ArchiveDetailsForm({
  match,
  busy,
  save,
}: {
  match: Match
  busy: boolean
  save: (body: object) => Promise<void>
}) {
  return (
    <form
      onSubmit={(event) => {
        event.preventDefault()
        const fields = new FormData(event.currentTarget)
        void save({
          game_day: fields.get('game_day'),
          start_time: fields.get('start_time') || null,
          location: fields.get('location'),
          season: fields.get('season'),
        })
      }}
    >
      <fieldset disabled={busy} className="archive-details-fields">
        <label>
          Дата игры
          <input name="game_day" type="date" defaultValue={match.game_day} required />
        </label>
        <label>
          Время игры · Москва
          <input
            name="start_time"
            type="time"
            defaultValue={(match.time_known ?? !match.historical) ? time(match.starts_at) : ''}
          />
        </label>
        <label>
          Место игры
          <input
            name="location"
            defaultValue={match.location === unknownLocation ? '' : match.location}
            minLength={2}
            maxLength={200}
            placeholder="Не указано"
          />
        </label>
        <label>
          Сезон
          <input name="season" defaultValue={match.season} minLength={1} maxLength={40} required />
        </label>
        <Button type="submit" disabled={busy}>
          Сохранить параметры
        </Button>
      </fieldset>
    </form>
  )
}

export function ArchivedGameScreen({
  match: m,
  players,
  admin,
  busy,
  run,
  revision,
  openLineup,
}: {
  match: Match
  players: Player[]
  admin: boolean
  busy: boolean
  run: Run
  revision: number
  openLineup: (id: number) => void
}) {
  const [panel, setPanel] = useState<'details' | 'result' | 'history' | null>(null)
  const [history, setHistory] = useState<History | null>(null)
  const [loaded, setLoaded] = useState<{ version: number; scores: Scores } | null>(null)
  const [error, setError] = useState('')
  const [retry, setRetry] = useState(0)
  useEffect(() => {
    let active = true
    setError('')
    if (!m.result) return
    void api<Scores>(`/matches/${m.id}/lineup`)
      .then((scores) => {
        if (active) setLoaded({ version: m.version, scores })
      })
      .catch((e) => {
        if (active) setError((e as Error).message)
      })
    return () => {
      active = false
    }
  }, [m.id, m.version, revision, retry, Boolean(m.result)])
  const result = m.result
  const rows =
    loaded?.version === m.version ? (loaded.scores.official_players ?? loaded.scores.players) : []
  const ratings = new Map(rows.map((row) => [`${row.player_id}:${row.position}`, row]))
  const score = (person: Participant): Average & { position: Position } => ({
    position: person.position,
    attack: ratings.get(`${person.player_id}:${person.position}`)?.attack ?? null,
    defense: ratings.get(`${person.player_id}:${person.position}`)?.defense ?? null,
  })
  const participants = result?.participants ?? []
  const name = (id: number | null) => (
    <PlayerName
      playerId={id}
      alias={participants.find((p) => p.player_id === id)?.alias || 'Автор неизвестен'}
    />
  )
  const knownTime = m.time_known ?? !m.historical
  const gameDate = new Date(m.starts_at)
    .toLocaleDateString('ru-RU', {
      day: 'numeric',
      month: 'long',
      year: 'numeric',
      timeZone: 'Europe/Moscow',
    })
    .replace(' г.', '')
  return (
    <div className="archived-game">
      <header className="archive-game-heading">
        <div className="eyebrow">АРХИВ · СЕЗОН {m.season}</div>
        <h1>{gameDate}</h1>
        <div className="archive-game-meta">
          <span>
            <Clock3 size={16} />
            {knownTime ? `${time(m.starts_at)} МСК` : 'Время не указано'}
          </span>
          <span>
            <MapPin size={16} />
            {m.location && m.location !== unknownLocation ? m.location : 'Место не указано'}
          </span>
        </div>
      </header>
      {admin && (
        <div className="archive-game-actions" aria-label="Действия администратора">
          <Button
            className="ghost compact"
            disabled={busy}
            onClick={() => setPanel(panel === 'details' ? null : 'details')}
          >
            <Pencil size={15} />
            Изменить игру
          </Button>
          {m.status !== 'cancelled' && (
            <Button
              className="ghost compact"
              disabled={busy}
              onClick={() => setPanel(panel === 'result' ? null : 'result')}
            >
              <CircleDot size={15} />
              Исправить результат
            </Button>
          )}
          <Button
            className="ghost compact"
            disabled={busy}
            onClick={() => {
              if (panel === 'history') {
                setPanel(null)
                return
              }
              void run(async () => {
                setHistory(await api<History>(`/matches/${m.id}/history`))
                setPanel('history')
              })
            }}
          >
            <HistoryIcon size={15} />
            История изменений
          </Button>
        </div>
      )}
      {admin && (panel === 'details' || panel === 'history') && (
        <section
          className="panel archive-editor"
          aria-label={panel === 'details' ? 'Параметры игры' : 'История изменений'}
        >
          <div className="section-title">
            <h2>{panel === 'details' ? 'Параметры игры' : 'История изменений'}</h2>
            <button
              className="icon-button"
              aria-label="Закрыть редактирование"
              disabled={busy}
              onClick={() => setPanel(null)}
            >
              <X size={18} />
            </button>
          </div>
          {panel === 'details' ? (
            <ArchiveDetailsForm
              key={m.version}
              match={m}
              busy={busy}
              save={async (body) => {
                let saved = false
                await run(async () => {
                  await api(`/matches/${m.id}/archive-details`, 'PUT', {
                    ...body,
                    version: m.version,
                  })
                  saved = true
                }, 'Параметры сохранены')
                if (saved) setPanel(null)
              }}
            />
          ) : (
            history && <MatchHistory history={history} />
          )}
        </section>
      )}
      {admin && panel === 'result' ? (
        <MatchResult
          match={m}
          players={players}
          admin
          busy={busy}
          run={run}
          initialEditing
          onDone={() => setPanel(null)}
        />
      ) : (
        <>
          {m.status === 'cancelled' ? (
            <section className="panel">
              <h2>Игра отменена</h2>
              <p>{m.cancellation_reason || 'Причина не указана'}</p>
            </section>
          ) : result ? (
            <>
              <section className="archive-scoreboard" aria-label="Счёт матча">
                <span>
                  <i className="archive-team-dot white" aria-hidden="true" />
                  Белые
                </span>
                <strong>
                  {result.score.white} : {result.score.black}
                </strong>
                <span>
                  <i className="archive-team-dot black" aria-hidden="true" />
                  Чёрные
                </span>
              </section>
              <p className="archive-outcome muted">
                {result.completed
                  ? result.score.white === result.score.black
                    ? 'Ничья'
                    : result.score.white > result.score.black
                      ? 'Победа белых'
                      : 'Победа чёрных'
                  : 'Результат не подтверждён'}
              </p>
              <div className="archive-strength" aria-label="Сила сбора">
                <span>Сила сбора</span>
                <strong>
                  Σ {total(participants.map(score))}{' '}
                  <small>(с вратарями: {total(participants.map(score), true)})</small>
                </strong>
              </div>
              <p className="muted caption">
                Сила — только полевые: атака + защита. В скобках — с защитой вратарей.
              </p>
              <div className="section-title">
                <h2>Составы и голы</h2>
                <Button className="ghost compact" onClick={() => openLineup(m.id)}>
                  На поле
                </Button>
              </div>
              {error && (
                <div className="alert error" role="alert">
                  Не удалось загрузить оценки.{' '}
                  <button disabled={busy} onClick={() => setRetry((n) => n + 1)}>
                    Повторить
                  </button>
                </div>
              )}
              <div className="archive-teams">
                {(['white', 'black'] as Team[]).map((team) => {
                  const people = participants
                    .filter((p) => p.team === team)
                    .sort(
                      (a, b) =>
                        Number(a.position !== 'keeper') - Number(b.position !== 'keeper') ||
                        a.alias.localeCompare(b.alias, 'ru') ||
                        a.player_id - b.player_id,
                    )
                  const goals = result.goals.filter((g) => g.team === team)
                  return (
                    <section
                      className="panel archive-team"
                      key={team}
                      aria-label={`${teamLabel(team)}: состав и голы`}
                    >
                      <div className="section-title">
                        <h3>
                          <i className={`archive-team-dot ${team}`} aria-hidden="true" />
                          {teamLabel(team)} <small className="muted">{people.length}</small>
                        </h3>
                        <strong aria-label={`Сила команды ${teamLabel(team)}`}>
                          Σ {total(people.map(score))}{' '}
                          <small>(с вратарями: {total(people.map(score), true)})</small>
                        </strong>
                      </div>
                      <table
                        className="archive-player-ratings"
                        aria-label={`Оценки игроков: ${teamLabel(team)}`}
                      >
                        <thead>
                          <tr>
                            <th>Игрок</th>
                            <th>
                              <RatingMark kind="attack" />
                            </th>
                            <th>
                              <RatingMark kind="defense" />
                            </th>
                            <th>Σ</th>
                          </tr>
                        </thead>
                        <tbody>
                          {people.map((person) => {
                            const rating = score(person)
                            return (
                              <tr key={person.player_id}>
                                <td>
                                  {person.position === 'keeper' && (
                                    <Hand size={13} aria-label="Вратарь" />
                                  )}
                                  <PlayerName playerId={person.player_id} alias={person.alias} />
                                </td>
                                <td>
                                  {person.position === 'keeper' ? '—' : ratingNumber(rating.attack)}
                                </td>
                                <td>{ratingNumber(rating.defense)}</td>
                                <td>{total([rating])}</td>
                              </tr>
                            )
                          })}
                        </tbody>
                      </table>
                      <div className="archive-goals">
                        <h4>Голы</h4>
                        {goals.length ? (
                          goals.map((goal) => (
                            <div className="archive-goal" key={goal.id}>
                              <CircleDot size={14} aria-hidden="true" />
                              <div>
                                {goal.kind === 'own_goal' ? (
                                  goal.author_id ? (
                                    <>{name(goal.author_id)} · автогол</>
                                  ) : (
                                    'Автогол'
                                  )
                                ) : (
                                  name(goal.author_id)
                                )}
                                {goal.assist_id && <small>Пас: {name(goal.assist_id)}</small>}
                              </div>
                            </div>
                          ))
                        ) : (
                          <p className="muted caption">Без голов</p>
                        )}
                      </div>
                    </section>
                  )
                })}
              </div>
            </>
          ) : (
            <p className="panel muted">Результат ещё не внесён.</p>
          )}
        </>
      )}
    </div>
  )
}
