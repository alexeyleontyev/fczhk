import { useRef, useState } from 'react'
import { ArrowLeftRight } from 'lucide-react'
import { percentTone } from './percent'
import type { ResultRow } from './leaderboards'
import { SectionTabs } from './section-tabs'

const columns = {
  games: [
    ['games', 'Игры', 'Игры'],
    ['points', 'Очки', 'Очки'],
    ['wins', 'В', 'Победы'],
    ['draws', 'Н', 'Ничьи'],
    ['losses', 'П', 'Поражения'],
    ['win_rate', 'ВР, %', 'Винрейт'],
  ],
  scoring: [
    ['games', 'Игры', 'Игры'],
    ['goals', 'Голы', 'Голы'],
    ['assists', 'Пасы', 'Пасы'],
    ['goal_assist', 'Г+П', 'Гол + пас'],
  ],
} as const
type View = keyof typeof columns
type Sort = 'rank' | 'alias' | (typeof columns)[View][number][0]

export function ResultsTable({
  rows,
  rankingRows,
  onPlayer,
}: {
  rows: ResultRow[]
  rankingRows: ResultRow[]
  onPlayer: (id: number) => void
}) {
  const [view, setView] = useState<View>('games')
  const scroll = useRef<HTMLDivElement>(null)
  const [sorting, setSorting] = useState<Record<View, { sort: Sort; ascending: boolean }>>({
    games: { sort: 'points', ascending: false },
    scoring: { sort: 'goal_assist', ascending: false },
  })
  const { sort, ascending } = sorting[view]
  const metrics = columns[view]
  const rankingMetric = view === 'games' ? 'points' : 'goal_assist'
  const [expanded, setExpanded] = useState(false)
  const rank = (row: ResultRow) =>
    1 + rankingRows.filter((p) => p[rankingMetric] > row[rankingMetric]).length
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
  function header(key: Sort, label: string, className = '', fullLabel = label) {
    return (
      <th
        key={key}
        scope="col"
        className={className}
        aria-sort={sort === key ? (ascending ? 'ascending' : 'descending') : 'none'}
      >
        <button
          className={`table-sort ${sort === key ? 'active' : ''}`}
          aria-label={fullLabel}
          title={fullLabel !== label ? fullLabel : undefined}
          onClick={() => {
            setSorting((old) => ({
              ...old,
              [view]: {
                sort: key,
                ascending: sort === key ? !ascending : key === 'alias' || key === 'rank',
              },
            }))
          }}
        >
          {label}
          <span aria-hidden="true">{sort === key ? (ascending ? '↑' : '↓') : '↕'}</span>
        </button>
      </th>
    )
  }
  return (
    <SectionTabs
      label="Вид зачёта"
      value={view}
      onChange={(next) => {
        setView(next)
        scroll.current?.scrollTo({ left: 0 })
      }}
      options={[
        { value: 'games', label: 'Игры' },
        { value: 'scoring', label: 'Голы и пасы' },
      ]}
    >
      <div
        className="table-scroll"
        ref={scroll}
        role="region"
        aria-label="Зачёты с горизонтальной прокруткой"
        tabIndex={0}
      >
        <table
          className={`results-table results-${view} compact-table`}
          aria-label={view === 'games' ? 'Зачёт по играм' : 'Зачёт по голам и пасам'}
        >
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
              {metrics.map(([key, label, fullLabel]) =>
                header(key, label, key === 'games' ? 'result-games' : '', fullLabel),
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
                        : key === rankingMetric
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
        <ArrowLeftRight size={14} /> Игрок и игры закреплены. Сортировка — по заголовку.
        <br />
        {view === 'games'
          ? 'Место — по очкам. В/Н/П — победы, ничьи, поражения; ВР — винрейт.'
          : 'Место — по Г+П: голы + пасы.'}
      </p>
      {rows.length > 10 && (
        <button className="button ghost compact" onClick={() => setExpanded(!expanded)}>
          {expanded ? 'Свернуть' : `Показать всех (${rows.length})`}
        </button>
      )}
    </SectionTabs>
  )
}
