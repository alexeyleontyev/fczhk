import { useEffect, useState } from 'react'
import { api } from './api'
import { Button } from './ui'
import type { Player } from './types'

export type Claim = {
  player_id: number
  guest_id: number
  player: string
  guest: string
  status: 'pending' | 'accepted' | 'rejected'
}

export function ProfileLink({ players }: { players: Player[] }) {
  const [claim, setClaim] = useState<Claim | null>(null)
  const [guest, setGuest] = useState('')
  const [search, setSearch] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  useEffect(() => {
    let active = true
    api<Claim | null>('/me/profile-claim')
      .then((value) => {
        if (active) setClaim(value)
      })
      .catch((e) => {
        if (active) setError(e.message)
      })
    return () => {
      active = false
    }
  }, [])
  async function submit() {
    setBusy(true)
    setError('')
    try {
      setClaim(await api<Claim>('/me/profile-claim', 'POST', { guest_id: Number(guest) }))
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }
  return (
    <section className="profile-link">
      <h3>Моя история игр</h3>
      <p>
        Если вы уже играли в клубе, выберите свою прежнюю карточку. Администратор проверит связь и
        объединит статистику. После подтверждения ваш игровой alias будет взят из исторической
        карточки.
      </p>
      {error && (
        <p role="alert" className="alert error">
          {error}
        </p>
      )}
      {claim && (
        <p role="status">
          {claim.status === 'pending'
            ? 'Ожидает подтверждения'
            : claim.status === 'accepted'
              ? 'Карточка привязана'
              : 'Заявка отклонена'}
          : {claim.guest}
        </p>
      )}
      {claim?.status !== 'accepted' && (
        <>
          <label>
            Поиск исторической карточки
            <input value={search} onChange={(e) => setSearch(e.target.value)} />
          </label>
          <label>
            Моя прежняя карточка
            <select value={guest} onChange={(e) => setGuest(e.target.value)}>
              <option value="">Выберите своё имя</option>
              {players
                .filter(
                  (p) =>
                    p.guest &&
                    !p.shared_keeper &&
                    p.alias.toLocaleLowerCase().includes(search.toLocaleLowerCase()),
                )
                .map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.alias}
                  </option>
                ))}
            </select>
          </label>
          <Button disabled={busy || !guest} className="secondary" onClick={() => void submit()}>
            Запросить привязку
          </Button>
        </>
      )}
    </section>
  )
}
