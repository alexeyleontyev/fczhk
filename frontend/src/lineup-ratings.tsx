import { useEffect, useId, useRef, useState } from 'react'
import { api } from './api'
import { PlayerName } from './player-name'
import { RatingMark, ratingNumber as fmt } from './rating-mark'
import type { Position, Team } from './types'

type Score = { attack: number | null; defense: number | null }
type Person = Score & {
  registration_id: number
  player_id: number
  alias: string
  position: Position
  game_mu?: number | null
}
type Author = { player_id: number; alias: string; ratings: Record<string, Score> }
type Metric = { value: number; known: number; count: number }
type Totals = Record<'attack' | 'defense' | 'total', Metric>
type Choice = Author & { rated: number; count: number; inLineup: boolean }
const COMMUNITY = 'community'
const teams: Team[] = ['white', 'black']
const metrics = ['attack', 'defense', 'total'] as const
const teamName = (team: Team) => (team === 'white' ? '⚪ Белые' : '⚫ Чёрные')
const normalize = (value: string) => value.toLocaleLowerCase('ru').replaceAll('ё', 'е').trim()

function totals(people: Person[], score: (p: Person) => Score | undefined): Totals {
  const sum = (kind: 'attack' | 'defense'): Metric => {
    const values = people.filter((p) => p.position === 'field').map((p) => score(p)?.[kind])
    const known = values.filter((value): value is number => value !== null && value !== undefined)
    return { value: known.reduce((a, b) => a + b, 0), known: known.length, count: values.length }
  }
  const attack = sum('attack'),
    defense = sum('defense')
  return {
    attack,
    defense,
    total: {
      value: attack.value + defense.value,
      known: attack.known + defense.known,
      count: attack.count + defense.count,
    },
  }
}

function metricValue(metric: Metric) {
  return metric.known ? `${metric.known < metric.count ? '≥ ' : ''}${fmt(metric.value)}` : '—'
}

function Metrics({ values }: { values: Record<'attack' | 'defense' | 'total', string> }) {
  return (
    <div className="lineup-rating-metrics">
      {metrics.map((kind) => (
        <span key={kind} className={kind === 'total' ? 'total' : ''}>
          <small>
            {kind === 'total' ? (
              'Σ Сумма'
            ) : (
              <>
                <RatingMark kind={kind} /> {kind === 'attack' ? 'Атака' : 'Защита'}
              </>
            )}
          </small>
          <b>{values[kind]}</b>
        </span>
      ))}
    </div>
  )
}

function SourcePicker({
  title,
  value,
  choices,
  onChange,
}: {
  title: string
  value: string
  choices: Choice[]
  onChange: (id: string) => void
}) {
  const [open, setOpen] = useState(false),
    [query, setQuery] = useState('')
  const id = useId(),
    toggle = useRef<HTMLButtonElement>(null)
  const search = normalize(query)
  const matches = choices.filter((author) =>
    search ? normalize(author.alias).includes(search) : author.inLineup,
  )
  const visible = matches.slice(0, 6)
  const choose = (next: string) => {
    onChange(next)
    setOpen(false)
    toggle.current?.focus()
  }
  return (
    <div className="lineup-rating-picker">
      <div className="lineup-rating-picker-heading">
        <div>
          <strong>{title}</strong>
          <small>Один источник для обеих команд</small>
        </div>
        <button
          type="button"
          className="lineup-rating-select"
          ref={toggle}
          aria-label={`Выбрать источник: ${title.toLocaleLowerCase('ru')}`}
          aria-controls={id}
          aria-expanded={open}
          onClick={() => {
            setOpen(!open)
            setQuery('')
          }}
        >
          <span>
            {value === COMMUNITY
              ? 'Общие оценки'
              : (choices.find((p) => String(p.player_id) === value)?.alias ?? 'Общие оценки')}
          </span>
          <small>Сменить</small>
        </button>
      </div>
      {open && (
        <div
          id={id}
          className="lineup-rating-search"
          onKeyDown={(event) => {
            if (event.key === 'Escape') {
              setOpen(false)
              toggle.current?.focus()
            }
          }}
        >
          <label htmlFor={`${id}-query`}>Найти оценивающего</label>
          <input
            id={`${id}-query`}
            type="search"
            autoFocus
            value={query}
            autoComplete="off"
            placeholder="Имя или прозвище"
            onChange={(e) => setQuery(e.target.value)}
          />
          <div className="lineup-rating-options">
            <button
              type="button"
              className="lineup-rating-general"
              aria-pressed={value === COMMUNITY}
              onClick={() => choose(COMMUNITY)}
            >
              Общие оценки
            </button>
            {visible.map((author) => (
              <button
                key={author.player_id}
                type="button"
                aria-pressed={value === String(author.player_id)}
                onClick={() => choose(String(author.player_id))}
              >
                {author.alias}
                <small>
                  Оценил {author.rated} из {author.count} полевых
                </small>
              </button>
            ))}
          </div>
          <p className="muted caption" role="status">
            {search
              ? matches.length
                ? `Найдено: ${matches.length}${matches.length > 6 ? '. Уточните имя' : ''}`
                : 'Оценивший игрок не найден'
              : matches.length
                ? `Из составов: ${Math.min(6, matches.length)} из ${matches.length} оценивших. Остальные — через поиск.`
                : 'В составах пока никто не выставил оценки. Поиск — по всем оценившим.'}
          </p>
        </div>
      )}
    </div>
  )
}

export function LineupRatings({
  matchId,
  version,
  people,
  assignments,
  showGameRating,
}: {
  matchId: number
  version: number
  people: Person[]
  assignments: Record<string, Team | null>
  showGameRating: boolean
}) {
  const [opinions, setOpinions] = useState<{ matchId: number; authors: Author[] } | null>(null)
  const [error, setError] = useState('')
  const [upper, setUpper] = useState(COMMUNITY),
    [lower, setLower] = useState<string | null>(null)
  const [retry, setRetry] = useState(0)
  useEffect(() => {
    let active = true,
      pending = false
    async function load() {
      if (pending) return
      pending = true
      try {
        const response = await api<{ authors: Author[] }>(`/matches/${matchId}/lineup/ratings`)
        if (active) {
          setOpinions({ matchId, authors: response.authors })
          setError('')
        }
      } catch (e) {
        if (active) setError((e as Error).message)
      } finally {
        pending = false
      }
    }
    void load()
    const timer = setInterval(() => void load(), 15000)
    return () => {
      active = false
      clearInterval(timer)
    }
  }, [matchId, version, retry])
  const assigned = people.filter((p) => assignments[p.registration_id])
  const lineup = assigned.length ? assigned : people
  const field = lineup.filter((p) => p.position === 'field')
  const lineupIds = new Set(lineup.map((p) => p.player_id))
  const choices: Choice[] = (opinions?.matchId === matchId ? opinions.authors : [])
    .map((author) => {
      const eligible = [...new Set(field.map((p) => p.player_id))].filter(
        (id) => id !== author.player_id,
      )
      return {
        ...author,
        rated: eligible.filter(
          (id) => author.ratings[id]?.attack != null && author.ratings[id]?.defense != null,
        ).length,
        count: eligible.length,
        inLineup: lineupIds.has(author.player_id),
      }
    })
    .filter((author) => author.rated > 0)
    .sort(
      (a, b) =>
        b.rated - a.rated || a.alias.localeCompare(b.alias, 'ru') || a.player_id - b.player_id,
    )
  const valid = (id: string | null) =>
    id && choices.some((p) => String(p.player_id) === id) ? id : COMMUNITY
  const selected = {
    upper: valid(upper),
    lower:
      lower === null
        ? String(choices.find((p) => p.inLineup)?.player_id ?? choices[0]?.player_id ?? COMMUNITY)
        : valid(lower),
  }
  const name = (source: string) =>
    source === COMMUNITY
      ? 'Общие оценки'
      : choices.find((p) => String(p.player_id) === source)!.alias
  const score = (source: string, person: Person): Score | undefined =>
    source === COMMUNITY
      ? person
      : choices.find((p) => String(p.player_id) === source)?.ratings[person.player_id]
  const sums = (source: string, team: Team) =>
    totals(
      assigned.filter((p) => assignments[p.registration_id] === team),
      (p) => score(source, p),
    )
  let partialDifference = false
  const difference = (team: Team) => {
    const a = sums(selected.upper, team),
      b = sums(selected.lower, team)
    return Object.fromEntries(
      metrics.map((kind) => {
        if (!a[kind].count || !b[kind].count) return [kind, '—']
        if (
          selected.upper !== selected.lower &&
          (a[kind].known < a[kind].count || b[kind].known < b[kind].count)
        ) {
          partialDifference = true
          return [kind, '—']
        }
        const delta = Math.round((a[kind].value - b[kind].value) * 100) / 100
        return [kind, delta > 0 ? `+${fmt(delta)}` : delta < 0 ? `−${fmt(-delta)}` : '0']
      }),
    ) as Record<'attack' | 'defense' | 'total', string>
  }
  const differences = Object.fromEntries(teams.map((team) => [team, difference(team)])) as Record<
    Team,
    Record<'attack' | 'defense' | 'total', string>
  >
  return (
    <section className="lineup-ratings" aria-label="Сравнение оценок составов">
      {(['upper', 'lower'] as const).map((side) => {
        const source = selected[side]
        return (
          <section
            key={side}
            className="lineup-rating-block"
            aria-label={side === 'upper' ? 'Основные оценки' : 'Оценки для сравнения'}
          >
            <SourcePicker
              title={side === 'upper' ? 'Основные оценки' : 'Оценки для сравнения'}
              value={source}
              choices={choices}
              onChange={side === 'upper' ? setUpper : setLower}
            />
            <div
              className={`lineup-rating-teams ${side === 'upper' ? 'tactics-scores' : ''}`}
              aria-label={side === 'upper' ? 'Баллы команд' : 'Баллы команд для сравнения'}
            >
              {teams.map((team) => {
                const members = assigned.filter((p) => assignments[p.registration_id] === team)
                const fields = members.filter((p) => p.position === 'field')
                const values = sums(source, team)
                const missing = fields.filter(
                  (p) => score(source, p)?.attack == null || score(source, p)?.defense == null,
                )
                return (
                  <div className="lineup-rating-team" key={team}>
                    <strong>
                      {teamName(team)} <small>{members.length}</small>
                    </strong>
                    <p className="muted caption">
                      {source === COMMUNITY ? 'Общие оценки' : `Оценки: ${name(source)}`}
                    </p>
                    <Metrics
                      values={
                        Object.fromEntries(
                          metrics.map((kind) => [kind, metricValue(values[kind])]),
                        ) as Record<'attack' | 'defense' | 'total', string>
                      }
                    />
                    {source !== COMMUNITY && (
                      <p className="muted caption">
                        Оценено {fields.length - missing.length} из {fields.length} полевых
                        {missing.length > 0 && (
                          <>
                            <br />
                            Без оценки: {missing.map((p) => p.alias).join(', ')}
                          </>
                        )}
                      </p>
                    )}
                    {side === 'upper' && showGameRating && (
                      <small className="tactics-mu">
                        OpenSkill μ: {fmt(fields.reduce((n, p) => n + (p.game_mu ?? 0), 0))}
                      </small>
                    )}
                    {side === 'lower' && (
                      <details className="lineup-rating-details">
                        <summary>Оценки по игрокам</summary>
                        <table>
                          <thead>
                            <tr>
                              <th>Игрок</th>
                              <th>А</th>
                              <th>З</th>
                            </tr>
                          </thead>
                          <tbody>
                            {fields.map((p) => (
                              <tr key={p.registration_id}>
                                <td>
                                  <PlayerName playerId={p.player_id} alias={p.alias} />
                                  {source === String(p.player_id) && (
                                    <small className="muted">Себя не оценивает</small>
                                  )}
                                </td>
                                <td>{fmt(score(source, p)?.attack ?? null)}</td>
                                <td>{fmt(score(source, p)?.defense ?? null)}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </details>
                    )}
                  </div>
                )
              })}
            </div>
            {side === 'upper' && (
              <p className="lineup-rating-note muted caption">
                Все суммы — только по полевым игрокам. Вратари не учитываются.
              </p>
            )}
          </section>
        )
      })}
      {!opinions && !error && (
        <p className="lineup-rating-note muted caption" role="status">
          Загружаем оценки игроков…
        </p>
      )}
      {error && (
        <p className="lineup-rating-note" role="alert">
          Не удалось обновить оценки: {error}{' '}
          <button type="button" className="text-button" onClick={() => setRetry(retry + 1)}>
            Повторить
          </button>
        </p>
      )}
      <section className="lineup-rating-difference" aria-label="Разница между источниками оценок">
        <h3>Разница: верхние − нижние</h3>
        <p className="muted caption">
          {name(selected.upper)} − {name(selected.lower)}
        </p>
        <div className="lineup-rating-teams">
          {teams.map((team) => (
            <div
              className="lineup-rating-team"
              key={team}
              aria-label={`Разница: ${team === 'white' ? 'Белые' : 'Чёрные'}`}
            >
              <strong>{teamName(team)}</strong>
              <Metrics values={differences[team]} />
            </div>
          ))}
        </div>
        {partialDifference && (
          <p className="muted caption">Прочерк — недостаточно оценок для точной разницы.</p>
        )}
      </section>
    </section>
  )
}
