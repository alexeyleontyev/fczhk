import { useEffect, useId, useRef, useState } from 'react'
import { ChevronLeft, ChevronRight } from 'lucide-react'
import { api, DATA_CHANGED } from './api'
import { RatingMark, ratingNumber } from './rating-mark'

type Point = {
  date: string
  at: string
  attack: number | null
  defense: number
  count?: number
  changes?: number
}
type History = {
  as_of: string
  timezone: string
  method: string
  field: Point[]
  keeper: Point[]
}
type Coordinate = { x: number; y: number }
const DAY = 86400000
const dayValue = (date: string) => Date.parse(`${date}T00:00:00Z`) / DAY
const dateAtDay = (day: number) => new Date(day * DAY).toISOString().slice(0, 10)
const dateLabel = (date: string, short = false) =>
  new Date(`${date}T12:00:00+03:00`)
    .toLocaleDateString('ru-RU', {
      timeZone: 'Europe/Moscow',
      day: 'numeric',
      month: short ? 'short' : 'long',
      ...(short ? {} : { year: 'numeric' }),
    })
    .replace(' г.', '')

function moscowDate(at: string) {
  const parts = new Intl.DateTimeFormat('en', {
    timeZone: 'Europe/Moscow',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).formatToParts(new Date(at))
  return ['year', 'month', 'day'].map((part) => parts.find((p) => p.type === part)!.value).join('-')
}

function smoothPath(points: Coordinate[]) {
  if (!points.length) return ''
  let path = `M${points[0].x.toFixed(3)},${points[0].y.toFixed(3)}`
  if (points.length === 1) return path
  const slopes = points.slice(1).map((p, i) => (p.y - points[i].y) / (p.x - points[i].x))
  const tangents = points.map((_, i) => {
    if (i === 0) return slopes[0]
    if (i === points.length - 1) return slopes[slopes.length - 1]
    const before = slopes[i - 1],
      after = slopes[i]
    return before * after <= 0 ? 0 : Math.sign(before) * Math.min(Math.abs(before), Math.abs(after))
  })
  for (let i = 1; i < points.length; i++) {
    const previous = points[i - 1],
      point = points[i],
      third = (point.x - previous.x) / 3
    // Bounded control points prevent invented peaks between actual daily values.
    path += `C${(previous.x + third).toFixed(3)},${(previous.y + tangents[i - 1] * third).toFixed(3)} ${(point.x - third).toFixed(3)},${(point.y - tangents[i] * third).toFixed(3)} ${point.x.toFixed(3)},${point.y.toFixed(3)}`
  }
  return path
}

export function RatingHistory({ playerId }: { playerId: number }) {
  const [data, setData] = useState<History | null>(null)
  const [error, setError] = useState('')
  const [revision, setRevision] = useState(0)
  const [loading, setLoading] = useState(true)
  const [position, setPosition] = useState<'field' | 'keeper'>('field')
  const [period, setPeriod] = useState<'all' | '7'>('all')
  const [selectedDate, setSelectedDate] = useState<string | null>(null)
  const [hoverDate, setHoverDate] = useState<string | null>(null)
  const [width, setWidth] = useState(300)
  const chart = useRef<HTMLButtonElement>(null)
  const chartId = `rating-history-${useId().replace(/:/g, '')}`
  const activePosition = data?.field.length ? (data.keeper.length ? position : 'field') : 'keeper'

  useEffect(() => {
    let active = true
    setError('')
    setLoading(true)
    api<History>(`/players/${playerId}/rating-history`)
      .then((value) => {
        if (active) setData(value)
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
  }, [playerId, revision])

  useEffect(() => {
    const changed = (event: Event) => {
      if ((event as CustomEvent<{ path: string }>).detail?.path === `/players/${playerId}/ratings`)
        setRevision((value) => value + 1)
    }
    window.addEventListener(DATA_CHANGED, changed)
    return () => window.removeEventListener(DATA_CHANGED, changed)
  }, [playerId])

  useEffect(() => {
    const element = chart.current
    if (!element) return
    const resize = () => {
      if (element.clientWidth) setWidth(element.clientWidth)
    }
    resize()
    const observer = new ResizeObserver(resize)
    observer.observe(element)
    return () => observer.disconnect()
  }, [data, activePosition, period])

  const heading = <h3>Динамика по дням</h3>
  const failure = error && (
    <p className="alert error" role="alert">
      {error}{' '}
      <button type="button" className="text-button" onClick={() => setRevision((v) => v + 1)}>
        Повторить
      </button>
    </p>
  )
  if (!data)
    return (
      <section className="rating-history" aria-label="Динамика общих оценок">
        {heading}
        {loading && (
          <p className="muted caption" role="status">
            Загружаем историю оценок…
          </p>
        )}
        {failure}
      </section>
    )
  const points = data[activePosition]
  if (!points.length)
    return (
      <section className="rating-history" aria-label="Динамика общих оценок">
        {heading}
        {failure}
        <p className="muted caption">График появится после первой оценки.</p>
      </section>
    )
  const today = dayValue(moscowDate(data.as_of))
  const start = period === '7' ? today - 6 : dayValue(points[0].date)
  const visible = points.filter((p) => dayValue(p.date) >= start)
  const carry = points.filter((p) => dayValue(p.date) < start).at(-1)
  const chosen =
    visible.find((p) => p.date === (hoverDate || selectedDate)) || visible.at(-1) || carry!
  const index = visible.findIndex((p) => p.date === chosen.date)
  const noChanges = visible.length === 0
  const left = 25,
    right = Math.max(width - 12, 80),
    top = 14,
    bottom = 181
  const from = start === today ? start - 0.5 : start
  const to = start === today ? today + 0.5 : today
  const x = (day: number) => left + ((day - from) / (to - from)) * (right - left)
  const y = (score: number) => bottom - (score / 5) * (bottom - top)
  const tickCount = width < 380 ? 3 : 5
  const ticks = [
    ...new Set(
      Array.from({ length: tickCount }, (_, i) =>
        Math.round(start + ((today - start) * i) / (tickCount - 1)),
      ),
    ),
  ]
  const plotted = [...visible]
  if (carry && (!visible.length || dayValue(visible[0].date) > start))
    plotted.unshift({ ...carry, date: dateAtDay(start) })
  const tail = plotted.at(-1)!
  if (dayValue(tail.date) < today) plotted.push({ ...tail, date: dateAtDay(today) })
  const metrics: ('attack' | 'defense')[] =
    activePosition === 'keeper' ? ['defense'] : ['attack', 'defense']
  const showDots = visible.length <= Math.floor((right - left) / 7)
  const choose = (date: string) => {
    setSelectedDate(date)
    setHoverDate(null)
  }
  const move = (direction: number) => {
    if (visible.length)
      choose(visible[Math.max(0, Math.min(visible.length - 1, index + direction))].date)
  }
  const nearest = (clientX: number) => {
    const box = chart.current!.getBoundingClientRect()
    const target = ((clientX - box.left) / box.width) * width
    return visible.reduce((best, p) =>
      Math.abs(x(dayValue(p.date)) - target) < Math.abs(x(dayValue(best.date)) - target) ? p : best,
    )
  }
  return (
    <section className="rating-history" aria-label="Динамика общих оценок" aria-busy={loading}>
      <div className="rating-history-heading">
        {heading}
        <span>Шкала 0–5</span>
      </div>
      <p className="muted caption">Последнее значение в каждый день с оценками</p>
      {failure}
      <div className="rating-history-controls">
        <div className="rating-history-periods" role="group" aria-label="Период истории оценок">
          {(
            [
              ['all', 'Вся история'],
              ['7', '7 дней'],
            ] as const
          ).map(([value, label]) => (
            <button
              key={value}
              type="button"
              aria-pressed={period === value}
              onClick={() => {
                setPeriod(value)
                setSelectedDate(null)
                setHoverDate(null)
              }}
            >
              {label}
            </button>
          ))}
        </div>
        {data.field.length > 0 && data.keeper.length > 0 && (
          <div className="rating-history-periods" role="group" aria-label="Амплуа в истории оценок">
            {(
              [
                ['field', 'Полевой'],
                ['keeper', 'Вратарь'],
              ] as const
            ).map(([value, label]) => (
              <button
                key={value}
                type="button"
                aria-pressed={position === value}
                onClick={() => {
                  setPosition(value)
                  setSelectedDate(null)
                  setHoverDate(null)
                }}
              >
                {label}
              </button>
            ))}
          </div>
        )}
      </div>
      <div className="rating-history-legend">
        {metrics.map((metric) => (
          <span key={metric}>
            <i className={metric} />
            {metric === 'attack' ? 'Атака' : 'Защита'}
          </span>
        ))}
      </div>
      <button
        type="button"
        ref={chart}
        className="rating-history-canvas"
        aria-label="График средних оценок: выберите дату нажатием или клавишами со стрелками"
        onClick={(e) => {
          if (e.detail > 0 && visible.length) choose(nearest(e.clientX).date)
        }}
        onPointerMove={(e) => {
          if (e.pointerType === 'mouse' && visible.length) setHoverDate(nearest(e.clientX).date)
        }}
        onPointerLeave={() => setHoverDate(null)}
        onKeyDown={(e) => {
          if (['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(e.key) && visible.length) {
            e.preventDefault()
            if (e.key === 'Home' || e.key === 'End')
              choose(visible[e.key === 'Home' ? 0 : visible.length - 1].date)
            else move(e.key === 'ArrowLeft' ? -1 : 1)
          }
        }}
      >
        <svg
          className="rating-history-chart"
          viewBox={`0 0 ${width} 218`}
          role="img"
          aria-labelledby={`${chartId}-title`}
        >
          <title id={`${chartId}-title`}>
            Общие оценки {activePosition === 'keeper' ? 'вратаря' : 'полевого'} по дням; шкала от
            нуля до пяти
          </title>
          <defs>
            <clipPath id={chartId}>
              <rect x={left - 6} y={top - 6} width={right - left + 12} height={bottom - top + 12} />
            </clipPath>
          </defs>
          {Array.from({ length: 6 }, (_, value) => (
            <g key={value} className="rating-history-grid">
              <line x1={left} x2={right} y1={y(value)} y2={y(value)} />
              <text x={2} y={y(value) + 4}>
                {value}
              </text>
            </g>
          ))}
          {ticks.map((day, i) => (
            <text
              className="rating-history-tick"
              key={day}
              x={x(day)}
              y={207}
              textAnchor={
                ticks.length === 1
                  ? 'middle'
                  : i === 0
                    ? 'start'
                    : i === ticks.length - 1
                      ? 'end'
                      : 'middle'
              }
            >
              {dateLabel(dateAtDay(day), true)}
            </text>
          ))}
          {metrics.map((metric) => (
            <g className={`rating-history-series ${metric}`} key={metric}>
              <path
                d={smoothPath(plotted.map((p) => ({ x: x(dayValue(p.date)), y: y(p[metric]!) })))}
                clipPath={`url(#${chartId})`}
              />
              {showDots &&
                visible.map((p) => (
                  <circle key={p.date} cx={x(dayValue(p.date))} cy={y(p[metric]!)} r={3} />
                ))}
            </g>
          ))}
          {!noChanges && (
            <g className="rating-history-selection">
              <line
                x1={x(dayValue(chosen.date))}
                x2={x(dayValue(chosen.date))}
                y1={top}
                y2={bottom}
              />
              {metrics.map((metric) => (
                <circle
                  key={metric}
                  className={metric}
                  cx={x(dayValue(chosen.date))}
                  cy={y(chosen[metric]!)}
                  r={5}
                />
              ))}
            </g>
          )}
        </svg>
      </button>
      <div
        className="rating-history-readout"
        aria-live={hoverDate ? 'off' : 'polite'}
        aria-atomic="true"
      >
        <div className="rating-history-date">
          <button
            type="button"
            aria-label="Предыдущая дата"
            disabled={index <= 0}
            onClick={() => move(-1)}
          >
            <ChevronLeft size={16} />
          </button>
          <div>
            <strong>
              {noChanges ? 'Последняя запись: ' : ''}
              {dateLabel(chosen.date)}
            </strong>
            {chosen.count !== undefined && (
              <div className="rating-history-meta">
                <span>Оценщиков: {chosen.count}</span>
                {chosen.changes ? <span>записей за день: {chosen.changes}</span> : null}
              </div>
            )}
          </div>
          <button
            type="button"
            aria-label="Следующая дата"
            disabled={index < 0 || index === visible.length - 1}
            onClick={() => move(1)}
          >
            <ChevronRight size={16} />
          </button>
        </div>
        <div className="rating-history-values">
          {metrics.map((metric) => (
            <span key={metric}>
              <RatingMark kind={metric} />
              <b>{ratingNumber(chosen[metric])}</b>
            </span>
          ))}
        </div>
        <p>{noChanges ? 'За 7 дней оценок не меняли' : 'Последнее значение за день'}</p>
      </div>
      <p className="muted caption rating-history-note">
        История — с первой сохранённой оценки или импорта. Все точки пересчитаны текущим методом;
        плавные линии соединяют известные значения.
      </p>
    </section>
  )
}
