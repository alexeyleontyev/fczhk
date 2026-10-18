import { useState } from 'react'
import { Plus, ArrowUpRight } from 'lucide-react'
import { Leaderboards } from './leaderboards'
import { GameRatingLeaderboard, RatingAverages } from './ratings'
import { initial } from './format'
import { Button } from './ui'
import type { Player } from './types'

export function PlayersScreen({
  players,
  me,
  dataRevision,
  openStats,
  setRatingTarget,
  setModal,
}: {
  players: Player[]
  me: Player
  dataRevision: number
  openStats: (id: number) => void
  setRatingTarget: (id: number | null) => void
  setModal: (value: string | null) => void
}) {
  const isAdmin = Boolean(me.is_admin)
  const [search, setSearch] = useState('')
  return (
    <>
      <div className="page-heading">
        <div>
          <div className="eyebrow">СВОИ НА ПОЛЕ</div>
          <h1>
            Игроки <span className="muted">{players.length}</span>
          </h1>
        </div>
        <div className="inline wrap">
          <Button
            onClick={() => {
              setRatingTarget(null)
              setModal('ratings')
            }}
          >
            Оценить игроков
          </Button>
          {isAdmin && (
            <Button onClick={() => setModal('guest')}>
              <Plus size={17} /> Гость
            </Button>
          )}
        </div>
      </div>
      <Leaderboards onPlayer={openStats} revision={dataRevision} />
      <GameRatingLeaderboard onPlayer={openStats} />
      <input
        className="search"
        placeholder="Найти по имени или alias"
        aria-label="Поиск игроков"
        value={search}
        onChange={(e) => setSearch(e.target.value)}
      />
      <div className="players-grid">
        {players
          .filter((p) => p.alias.toLowerCase().includes(search.toLowerCase()))
          .map((p) => (
            <div key={p.id} className="panel player-card">
              <span className="avatar">{initial(p.alias)}</span>
              <div>
                <h3>{p.alias}</h3>
                <span className="muted">{p.guest ? 'Гость' : 'Игрок клуба'}</span>
                <RatingAverages player={p} />
                <button className="button ghost compact" onClick={() => openStats(p.id)}>
                  Статистика
                </button>
                {(p.id !== me.id || isAdmin) && (
                  <button
                    className="button ghost compact"
                    aria-label={`Оценки: ${p.alias}`}
                    onClick={() => {
                      setRatingTarget(p.id)
                      setModal('ratings')
                    }}
                  >
                    {p.id === me.id ? 'Посмотреть оценки' : 'Оценить'}
                  </button>
                )}
              </div>
              {isAdmin && p.guest && (
                <button
                  className="icon-button"
                  aria-label={`Связать гостя ${p.alias}`}
                  onClick={() => setModal(`link:${p.id}`)}
                >
                  <ArrowUpRight size={18} />
                </button>
              )}
            </div>
          ))}
      </div>
    </>
  )
}
