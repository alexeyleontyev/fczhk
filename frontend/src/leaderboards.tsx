import { useEffect, useState, type ReactNode } from 'react'
import { api } from './api'
import { seasonQuery } from './seasons'
import { ResultsTable } from './results-table'
import { DEFAULT_MIN_GAMES, filterPlayerNames, filterPlayers } from './player-list-filters'
import { RatingPair, RatingMark } from './rating-mark'

type ResultMetric = 'points' | 'win_rate' | 'goals' | 'assists' | 'goal_assist'
type CommunityMetric = 'field_total' | 'field_attack' | 'field_defense' | 'keeper_defense'
export type ResultRow = {
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
    <label className="compact-metric">
      Показатель
      <select
        aria-label="Показатель зачёта"
        value={selected}
        onChange={(e) => select(e.target.value as T)}
      >
        {options.map(({ key, label }) => (
          <option key={key} value={key}>
            {label}
          </option>
        ))}
      </select>
    </label>
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
  columns,
  valueLabel = 'Баллы',
}: {
  columns?: { label: ReactNode; value: (row: T) => ReactNode }[]
  valueLabel?: ReactNode
  rows: T[]
  rankingRows?: T[]
  value: (row: T) => number
  formatValue?: (row: T) => string
  valueClassName?: (row: T) => string
  details: (row: T) => ReactNode
  onPlayer: (id: number) => void
}) {
  const [expanded, setExpanded] = useState(false)
  const shown = expanded ? rows : rows.slice(0, 10)
  return (
    <>
      <table className="compact-table leaderboard-list">
        <thead>
          <tr>
            <th className="rank-column">№</th>
            <th>Игрок</th>
            {columns ? columns.map((c, i) => <th key={i}>{c.label}</th>) : <th>Игры</th>}
            <th>{valueLabel}</th>
          </tr>
        </thead>
        <tbody>
          {shown.map((row) => (
            <tr className="leaderboard-row" key={row.player_id}>
              <td className="muted">
                {rankingRows.findIndex((candidate) => value(candidate) === value(row)) + 1}
              </td>
              <td>
                <button className="text-button" onClick={() => onPlayer(row.player_id)}>
                  {row.alias}
                </button>
              </td>
              {columns ? (
                columns.map((c, i) => <td key={i}>{c.value(row)}</td>)
              ) : (
                <td>{details(row)}</td>
              )}
              <td className={valueClassName?.(row)}>
                <strong>
                  {formatValue?.(row) ??
                    value(row).toLocaleString('ru-RU', { maximumFractionDigits: 1 })}
                </strong>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
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
  season,
  mode,
  name,
}: {
  mode: 'results' | 'community'
  name: string
  season: string
  onPlayer: (id: number) => void
  revision: number
}) {
  const [data, setData] = useState<Boards | null>(null)
  const [error, setError] = useState('')
  const [communityMetric, setCommunityMetric] = useState<CommunityMetric>('field_total')
  const [resultMinimumGames, setResultMinimumGames] = useState(DEFAULT_MIN_GAMES)
  useEffect(() => {
    let active = true
    setError('')
    setData(null)
    void api<Boards>(`/leaderboards${seasonQuery(season)}`)
      .then((value) => {
        if (active) setData(value)
      })
      .catch((e) => {
        if (active) setError((e as Error).message)
      })
    return () => {
      active = false
    }
  }, [revision, season])
  const allResultRows = data?.results.boards.points ?? []
  const qualifiedResultRows = filterPlayers(allResultRows, '', resultMinimumGames)
  const resultRows = filterPlayers(qualifiedResultRows, name, '0')
  const allCommunityRows = data?.community.boards[communityMetric] ?? []
  const communityRows = filterPlayerNames(allCommunityRows, name)
  return (
    <>
      {mode === 'results' && (
        <section className="panel leaderboard-board">
          <div className="section-title">
            <div>
              <div className="eyebrow">ПО РЕЗУЛЬТАТАМ МАТЧЕЙ</div>
              <h2>{season ? `Зачёты сезона ${season}` : 'Общие зачёты'}</h2>
            </div>
          </div>
          <details className="compact-explanation">
            <summary>Как считается зачёт</summary>
            <p className="muted caption">
              {data ? `${data.results.matches} завершённых игр. ` : ''}В зачёте очков: победа — 3,
              ничья — 1, поражение — 0. Винрейт: победа — 2, ничья — 1, поражение — 0 из 2 за игру.
              Автоголы не входят в зачёт бомбардиров.
            </p>
          </details>
          <label className="compact-minimum">
            Игр больше
            <input
              type="number"
              min="0"
              value={resultMinimumGames}
              onChange={(e) => setResultMinimumGames(e.target.value)}
            />
          </label>
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
          {data && allResultRows.length > 0 && (
            <ResultsTable rows={resultRows} rankingRows={qualifiedResultRows} onPlayer={onPlayer} />
          )}
        </section>
      )}
      {mode === 'community' && (
        <section className="panel leaderboard-board">
          <div className="section-title">
            <div>
              <div className="eyebrow">ОЦЕНКИ УЧАСТНИКОВ</div>
              <h2>Рейтинг сообщества</h2>
            </div>
          </div>
          <details className="compact-explanation">
            <summary>Оценки общие для всех сезонов</summary>
            <p className="muted caption">
              Оценки сообщества общие для всех сезонов. Средние оценки за полевую игру или игру в
              воротах. В общем зачёте складываются средние оценки атаки и защиты; игроки без оценок
              по выбранному показателю не показаны.
            </p>
          </details>
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
          {data && !allCommunityRows.length && <p>По этому показателю оценок пока нет.</p>}
          {data && allCommunityRows.length > 0 && !communityRows.length && (
            <p>Игроки с таким именем не найдены.</p>
          )}
          {data && communityRows.length > 0 && (
            <LeaderboardRows
              key={communityMetric}
              columns={
                communityMetric === 'field_total'
                  ? [
                      {
                        label: <RatingMark kind="attack" />,
                        value: (row) =>
                          row.attack?.toLocaleString('ru-RU', { maximumFractionDigits: 2 }) ?? '—',
                      },
                      {
                        label: <RatingMark kind="defense" />,
                        value: (row) =>
                          row.defense.toLocaleString('ru-RU', { maximumFractionDigits: 2 }),
                      },
                    ]
                  : []
              }
              valueLabel={
                communityMetric === 'field_total' ? (
                  'Σ'
                ) : (
                  <RatingMark kind={communityMetric === 'field_attack' ? 'attack' : 'defense'} />
                )
              }
              rows={communityRows}
              rankingRows={allCommunityRows}
              onPlayer={onPlayer}
              value={(row) => row.score}
              formatValue={(row) => row.score.toLocaleString('ru-RU', { maximumFractionDigits: 2 })}
              details={(row) =>
                communityMetric === 'keeper_defense' ? (
                  'Вратарь'
                ) : (
                  <RatingPair attack={row.attack} defense={row.defense} />
                )
              }
            />
          )}
        </section>
      )}
    </>
  )
}
