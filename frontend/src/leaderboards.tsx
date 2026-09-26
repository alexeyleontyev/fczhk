import { useEffect, useState } from 'react'
import { api } from './api'
import { percentTone } from './percent'
import { DEFAULT_MIN_GAMES, filterPlayers, PlayerListFilters } from './player-list-filters'
import { score } from './ratings'

type ResultMetric = 'points' | 'win_rate' | 'goals' | 'assists' | 'goal_assist'
type CommunityMetric = 'field_total' | 'field_attack' | 'field_defense' | 'keeper_defense'
type ResultRow = {
  player_id: number
  alias: string
  games: number
  wins: number
  draws: number
  losses: number
  points: number
  win_rate: number
  goals: number
  assists: number
  goal_assist: number
}
type CommunityRow = {
  player_id: number
  alias: string
  score: number
  attack: number | null
  defense: number
}
type Boards = {
  results: { matches: number; boards: Record<ResultMetric, ResultRow[]> }
  community: { boards: Record<CommunityMetric, CommunityRow[]> }
}

const resultOptions: { key: ResultMetric; label: string }[] = [
  { key: 'points', label: 'Очки' },
  { key: 'win_rate', label: 'Винрейт' },
  { key: 'goals', label: 'Голы' },
  { key: 'assists', label: 'Передачи' },
  { key: 'goal_assist', label: 'Гол + пас' },
]
const communityOptions: { key: CommunityMetric; label: string }[] = [
  { key: 'field_total', label: 'Атака + защита' },
  { key: 'field_attack', label: 'Атака' },
  { key: 'field_defense', label: 'Защита' },
  { key: 'keeper_defense', label: 'Защита вратаря' },
]

function Filters<T extends string>({
  options,
  selected,
  select,
}: {
  options: { key: T; label: string }[]
  selected: T
  select: (metric: T) => void
}) {
  return (
    <div className="leaderboard-filters" role="group" aria-label="Показатель зачёта">
      {options.map(({ key, label }) => (
        <button
          key={key}
          type="button"
          className={selected === key ? 'active' : ''}
          aria-pressed={selected === key}
          onClick={() => select(key)}
        >
          {label}
        </button>
      ))}
    </div>
  )
}

function LeaderboardRows<T extends { player_id: number; alias: string }>({
  rows,
  rankingRows = rows,
  value,
  formatValue,
  valueClassName,
  details,
  onPlayer,
}: {
  rows: T[]
  rankingRows?: T[]
  value: (row: T) => number
  formatValue?: (row: T) => string
  valueClassName?: (row: T) => string
  details: (row: T) => string
  onPlayer: (id: number) => void
}) {
  const [expanded, setExpanded] = useState(false)
  const shown = expanded ? rows : rows.slice(0, 10)
  return (
    <>
      <div className="leaderboard-list">
        {shown.map((row) => {
          const rank = rankingRows.findIndex((candidate) => value(candidate) === value(row)) + 1
          return (
            <div className="leaderboard-row" key={row.player_id}>
              <span className="muted" aria-label={`Место ${rank}`}>
                {rank}
              </span>
              <button className="button ghost compact" onClick={() => onPlayer(row.player_id)}>
                {row.alias}
              </button>
              <small className="muted">{details(row)}</small>
              <strong className={valueClassName?.(row)}>
                {formatValue?.(row) ??
                  value(row).toLocaleString('ru-RU', { maximumFractionDigits: 1 })}
              </strong>
            </div>
          )
        })}
      </div>
      {rows.length > 10 && (
        <button className="button ghost compact" onClick={() => setExpanded(!expanded)}>
          {expanded ? 'Свернуть' : `Показать всех (${rows.length})`}
        </button>
      )}
    </>
  )
}

export function Leaderboards({
  onPlayer,
  revision,
}: {
  onPlayer: (id: number) => void
  revision: number
}) {
  const [data, setData] = useState<Boards | null>(null)
  const [error, setError] = useState('')
  const [resultMetric, setResultMetric] = useState<ResultMetric>('points')
  const [communityMetric, setCommunityMetric] = useState<CommunityMetric>('field_total')
  const [resultName, setResultName] = useState('')
  const [resultMinimumGames, setResultMinimumGames] = useState(DEFAULT_MIN_GAMES)
  useEffect(() => {
    let active = true
    setError('')
    void api<Boards>('/leaderboards')
      .then((value) => {
        if (active) setData(value)
      })
      .catch((e) => {
        if (active) setError((e as Error).message)
      })
    return () => {
      active = false
    }
  }, [revision])
  const allResultRows = data?.results.boards[resultMetric] ?? []
  const qualifiedResultRows = filterPlayers(allResultRows, '', resultMinimumGames)
  const resultRows = filterPlayers(qualifiedResultRows, resultName, '0')
  const communityRows = data?.community.boards[communityMetric] ?? []
  return (
    <>
      <section className="panel leaderboard-board">
        <div className="section-title">
          <div>
            <div className="eyebrow">ПО РЕЗУЛЬТАТАМ МАТЧЕЙ</div>
            <h2>Общие зачёты</h2>
          </div>
        </div>
        <p className="muted caption">
          {data ? `${data.results.matches} завершённых игр. ` : ''}В зачёте очков: победа — 3, ничья
          — 1, поражение — 0. Винрейт: победа — 2, ничья — 1, поражение — 0 из 2 за игру. Автоголы
          не входят в зачёт бомбардиров.
        </p>
        <Filters options={resultOptions} selected={resultMetric} select={setResultMetric} />
        <PlayerListFilters
          name={resultName}
          setName={setResultName}
          minimumGames={resultMinimumGames}
          setMinimumGames={setResultMinimumGames}
          scope="Фильтры общих зачётов"
        />
        {error && (
          <p role="alert" className="alert error">
            {error}
          </p>
        )}
        {!data && !error && <p className="muted">Загрузка…</p>}
        {data && !allResultRows.length && <p>Завершённых игр пока нет.</p>}
        {data && allResultRows.length > 0 && !resultRows.length && (
          <p>По выбранным фильтрам игроки не найдены.</p>
        )}
        {data && resultRows.length > 0 && (
          <LeaderboardRows
            key={resultMetric}
            rows={resultRows}
            rankingRows={qualifiedResultRows}
            onPlayer={onPlayer}
            value={(row) => row[resultMetric]}
            formatValue={
              resultMetric === 'win_rate'
                ? (row) => `${row.win_rate.toLocaleString('ru-RU', { maximumFractionDigits: 1 })}%`
                : undefined
            }
            valueClassName={
              resultMetric === 'win_rate' ? (row) => percentTone(row.win_rate) : undefined
            }
            details={(row) =>
              resultMetric === 'points'
                ? `${row.games} игр · ${row.wins} побед · ${row.draws} ничьих`
                : resultMetric === 'win_rate'
                  ? `${row.games} игр`
                  : `${row.games} игр · ${row.goals} голов · ${row.assists} передач`
            }
          />
        )}
      </section>
      <section className="panel leaderboard-board">
        <div className="section-title">
          <div>
            <div className="eyebrow">ОЦЕНКИ УЧАСТНИКОВ</div>
            <h2>Рейтинг сообщества</h2>
          </div>
        </div>
        <p className="muted caption">
          Средние оценки за полевую игру или игру в воротах. В общем зачёте складываются средние
          оценки атаки и защиты; игроки без оценок по выбранному показателю не показаны.
        </p>
        <Filters
          options={communityOptions}
          selected={communityMetric}
          select={setCommunityMetric}
        />
        {error && (
          <p role="alert" className="alert error">
            {error}
          </p>
        )}
        {!data && !error && <p className="muted">Загрузка…</p>}
        {data && !communityRows.length && <p>По этому показателю оценок пока нет.</p>}
        {data && communityRows.length > 0 && (
          <LeaderboardRows
            key={communityMetric}
            rows={communityRows}
            onPlayer={onPlayer}
            value={(row) => row.score}
            formatValue={(row) => row.score.toLocaleString('ru-RU', { maximumFractionDigits: 2 })}
            details={(row) =>
              communityMetric === 'keeper_defense'
                ? 'Вратарь'
                : `А ${score(row.attack)} · З ${score(row.defense)}`
            }
          />
        )}
      </section>
    </>
  )
}
