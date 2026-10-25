import { useState } from 'react'
import { ArrowLeftRight } from 'lucide-react'
import { percentTone } from './percent'
import type { ResultRow } from './leaderboards'

const metrics = [
  ['games', 'Игры'],
  ['points', 'Очки'],
  ['wins', 'Победы'],
  ['draws', 'Ничьи'],
  ['losses', 'Поражения'],
  ['goals', 'Голы'],
  ['assists', 'Передачи'],
  ['goal_assist', 'Гол + пас'],
  ['win_rate', 'Винрейт'],
] as const
type Sort = 'rank' | 'alias' | (typeof metrics)[number][0]

export function ResultsTable({
  rows,
  rankingRows,
  onPlayer,
}: {
  rows: ResultRow[]
  rankingRows: ResultRow[]
  onPlayer: (id: number) => void
}) {
  const [sort, setSort] = useState<Sort>('points')
  const [ascending, setAscending] = useState(false)
  const [expanded, setExpanded] = useState(false)
  const rank = (row: ResultRow) => rankingRows.findIndex((p) => p.points === row.points) + 1
  const value = (row: ResultRow, key: Sort) => (key === 'rank' ? rank(row) : row[key])
  const ordered = [...rows].sort((a, b) => {
    const x = value(a, sort),
      y = value(b, sort)
    return (
      (typeof x === 'string' && typeof y === 'string'
        ? x.localeCompare(y, 'ru')
        : Number(x) - Number(y)) * (ascending ? 1 : -1) ||
      a.alias.localeCompare(b.alias, 'ru') ||
      a.player_id - b.player_id
    )
  })
  function header(key: Sort, label: string, className = '') {
    return (
      <th
        key={key}
        scope="col"
        className={className}
        aria-sort={sort === key ? (ascending ? 'ascending' : 'descending') : 'none'}
      >
        <button
          className={`table-sort ${sort === key ? 'active' : ''}`}
          onClick={() => {
            setAscending(sort === key ? !ascending : key === 'alias' || key === 'rank')
            setSort(key)
          }}
        >
          {label}
          <span aria-hidden="true">{sort === key ? (ascending ? '↑' : '↓') : '↕'}</span>
        </button>
      </th>
    )
  }
  return (
    <>
      <div
        className="table-scroll"
        role="region"
        aria-label="Зачёты с горизонтальной прокруткой"
        tabIndex={0}
      >
        <table className="results-table compact-table">
          <colgroup>
            <col className="result-rank-col" />
            <col className="result-name-col" />
            <col className="result-games-col" />
            {metrics.slice(1).map(([key]) => (
              <col key={key} className={`result-${key}-col`} />
            ))}
          </colgroup>
          <thead>
            <tr>
              {header('rank', '№', 'result-rank')}
              {header('alias', 'Игрок', 'result-name')}
              {metrics.map(([key, label]) =>
                header(key, label, key === 'games' ? 'result-games' : ''),
              )}
            </tr>
          </thead>
          <tbody>
            {(expanded ? ordered : ordered.slice(0, 10)).map((row) => (
              <tr key={row.player_id}>
                <td className="result-rank muted">{rank(row)}</td>
                <td className="result-name">
                  <button className="text-button" onClick={() => onPlayer(row.player_id)}>
                    {row.alias}
                  </button>
                </td>
                {metrics.map(([key]) => (
                  <td
                    key={key}
                    className={
                      key === 'games'
                        ? 'result-games'
                        : key === 'points'
                          ? 'result-points'
                          : key === 'win_rate'
                            ? percentTone(row.win_rate)
                            : ''
                    }
                  >
                    {key === 'win_rate'
                      ? `${row.win_rate.toLocaleString('ru-RU', { maximumFractionDigits: 1 })}%`
                      : row[key]}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="table-footnote">
        <ArrowLeftRight size={14} /> Листайте таблицу. Игрок и игры закреплены слева.
        <br />
        Нажмите на заголовок для сортировки.
      </p>
      {rows.length > 10 && (
        <button className="button ghost compact" onClick={() => setExpanded(!expanded)}>
          {expanded ? 'Свернуть' : `Показать всех (${rows.length})`}
        </button>
      )}
    </>
  )
}
