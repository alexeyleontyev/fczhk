import { useEffect, useRef, useState } from 'react'
import { Timer } from 'lucide-react'
import { api } from './api'
import { date, time } from './format'
import type { Match } from './types'

type Schedule = {
  server_now: string
  opening_at: string | null
  starts_at: string | null
  location: string | null
}

export function CollectionCountdown({
  refresh,
  currentGame,
}: {
  refresh: () => Promise<void>
  currentGame: Match | null
}) {
  const [schedule, setSchedule] = useState<Schedule | null>(null)
  const [remaining, setRemaining] = useState(0)
  const [error, setError] = useState('')
  const refreshRef = useRef(refresh)
  refreshRef.current = refresh

  useEffect(() => {
    let active = true
    let pending = false
    let anchor: { at: number; seconds: number } | null = null
    let lastLoad = -Infinity
    const tick = () => {
      if (!active || !anchor) return
      const seconds = Math.max(
        0,
        Math.ceil(anchor.seconds - (performance.now() - anchor.at) / 1000),
      )
      setRemaining(seconds)
      if (seconds === 0 && performance.now() - lastLoad >= 3000) void load(true)
    }
    const load = async (reachedOpening = false) => {
      if (!active || pending) return
      pending = true
      lastLoad = performance.now()
      try {
        const data = await api<Schedule>('/schedule/next')
        if (!active) return
        setSchedule(data)
        setError('')
        anchor = data.opening_at
          ? {
              at: performance.now(),
              seconds: (Date.parse(data.opening_at) - Date.parse(data.server_now)) / 1000,
            }
          : null
        if (anchor) setRemaining(Math.max(0, Math.ceil(anchor.seconds)))
        if (reachedOpening) await refreshRef.current()
      } catch {
        if (active) setError('Не удалось обновить расписание сбора')
      } finally {
        pending = false
      }
    }
    void load()
    const clock = window.setInterval(tick, 1000)
    const synchronize = window.setInterval(() => void load(), 30000)
    const visible = () => {
      if (document.visibilityState === 'visible') void load(true)
    }
    document.addEventListener('visibilitychange', visible)
    return () => {
      active = false
      window.clearInterval(clock)
      window.clearInterval(synchronize)
      document.removeEventListener('visibilitychange', visible)
    }
  }, [])

  if (!schedule?.opening_at)
    return error ? (
      <p className="muted caption" role="status">
        {error}
      </p>
    ) : null
  // Do not distract from an upcoming game with next week's collection timer.
  if (
    currentGame &&
    !['completed', 'cancelled'].includes(currentGame.status) &&
    Date.parse(currentGame.starts_at) > Date.parse(schedule.server_now)
  )
    return null
  const days = Math.floor(remaining / 86400)
  const clock = [Math.floor(remaining / 3600) % 24, Math.floor(remaining / 60) % 60, remaining % 60]
    .map((value) => String(value).padStart(2, '0'))
    .join(':')
  return (
    <section className="panel collection-countdown" aria-label="Отсчёт до открытия сбора">
      <div>
        <strong>
          <Timer size={18} aria-hidden="true" /> Следующий сбор
        </strong>
        <p className="muted caption">
          {date(schedule.opening_at)} · {time(schedule.opening_at)} МСК
        </p>
        {schedule.starts_at && (
          <p className="muted caption">
            Игра {date(schedule.starts_at)} · {time(schedule.starts_at)} МСК
          </p>
        )}
      </div>
      <div className="countdown-value" role="timer" aria-label="Осталось до открытия сбора">
        {remaining ? (
          <>
            {days > 0 && <span>{days} д. </span>}
            {clock}
          </>
        ) : (
          'Сбор открывается…'
        )}
      </div>
      {error && (
        <p className="muted caption" role="status">
          {error}
        </p>
      )}
    </section>
  )
}
