import { useEffect, useState } from 'react'
import { ArrowUpRight } from 'lucide-react'
import { api } from './api'
import { SeasonSelect, seasonQuery, type SeasonFilter } from './seasons'
import { date, time, status } from './format'
import { Button, Empty } from './ui'
import type { MatchSummary } from './types'

export function ArchiveScreen({
  onMatch,
  revision,
  ...seasonFilter
}: SeasonFilter & {
  onMatch: (id: number) => void
  revision: number
}) {
  const [games, setGames] = useState<MatchSummary[]>([])
  const [busy, setBusy] = useState(false)
  const [more, setMore] = useState(true)
  const [error, setError] = useState('')
  useEffect(() => {
    let active = true
    setBusy(true)
    api<MatchSummary[]>(`/matches?limit=20${seasonQuery(seasonFilter.season).replace('?', '&')}`)
      .then((rows) => {
        if (active) {
          setGames(rows)
          setMore(rows.length === 20)
          setError('')
        }
      })
      .catch((e) => {
        if (active) setError(e.message)
      })
      .finally(() => {
        if (active) setBusy(false)
      })
    return () => {
      active = false
    }
  }, [revision, seasonFilter.season])
  async function loadMore() {
    setBusy(true)
    try {
      const rows = await api<MatchSummary[]>(
        `/matches?limit=20&offset=${games.length}${seasonQuery(seasonFilter.season).replace('?', '&')}`,
      )
      setGames((old) => [...old, ...rows])
      setMore(rows.length === 20)
      setError('')
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }
  return (
    <>
      <div className="page-heading">
        <div className="eyebrow">НАША ИСТОРИЯ</div>
        <h1>Все игры</h1>
      </div>
      <SeasonSelect {...seasonFilter} />
      <p className="muted caption archive-legend">Счёт: белые : чёрные</p>
      {error && (
        <p className="alert error" role="alert">
          {error}
        </p>
      )}
      <div className="panel archive-grid compact-archive">
        {games.map((game) => (
          <button className="archive-card" key={game.id} onClick={() => onMatch(game.id)}>
            <span className="archive-date">
              <h2>{date(game.starts_at)}</h2>
              <small className="muted">
                Сезон {game.season} · {game.participant_count} игроков
              </small>
            </span>
            <strong className="archive-score">
              {game.result
                ? `${game.result.score.white} : ${game.result.score.black}`
                : !(game.time_known ?? !game.historical)
                  ? '—'
                  : `${time(game.starts_at)}`}
              {game.result && !game.result.completed && <small>черновик</small>}
            </strong>
            <span className={`status-pill ${game.status}`}>{status[game.status]}</span>
            <ArrowUpRight size={16} />
          </button>
        ))}
      </div>
      {!games.length && !busy && !error && (
        <Empty
          title="История начинается здесь"
          text="Созданные игры и их составы будут сохраняться в архиве."
        />
      )}
      {more && (
        <Button disabled={busy} className="secondary" onClick={() => void loadMore()}>
          {busy ? 'Загружаем…' : 'Показать ещё'}
        </Button>
      )}
    </>
  )
}
