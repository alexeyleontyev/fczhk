import { useState } from 'react'
import { api } from './api'
import { PlayerName } from './player-name'
import { RatingPair } from './rating-mark'

type Review = { author_id: number; author: string; attack: number | null; defense: number }
type Reviews = Record<'field' | 'keeper', Review[]>

export function PlayerReviews({ playerId }: { playerId: number }) {
  const [data, setData] = useState<Reviews | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  async function load() {
    setLoading(true)
    setError('')
    try {
      setData(await api<Reviews>(`/players/${playerId}/reviews`))
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setLoading(false)
    }
  }
  return (
    <details
      className="profile-reviews"
      onToggle={(event) => {
        if (event.currentTarget.open && !data && !loading) void load()
      }}
    >
      <summary>Как оценили другие игроки</summary>
      {loading && <p role="status">Загружаем оценки…</p>}
      {error && (
        <p className="alert error" role="alert">
          {error}{' '}
          <button type="button" className="text-button" onClick={() => void load()}>
            Повторить
          </button>
        </p>
      )}
      {data &&
        (['field', 'keeper'] as const).map((position) => (
          <div key={position}>
            <h4>{position === 'field' ? 'Полевой' : 'Вратарь'}</h4>
            {!data[position].length && <p className="muted caption">Оценок пока нет.</p>}
            {data[position].map((review) => (
              <div className="profile-review" key={review.author_id}>
                <PlayerName playerId={review.author_id} alias={review.author} />
                <RatingPair
                  attack={review.attack}
                  defense={review.defense}
                  keeper={position === 'keeper'}
                />
              </div>
            ))}
          </div>
        ))}
    </details>
  )
}
