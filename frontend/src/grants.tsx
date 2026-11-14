import { useEffect, useState } from 'react'

import { api } from './api'
import { points } from './betting'

type PendingRequest = {
  id: number
  player_id: number
  alias: string
  amount: number
  balance: number
  created_at: string
}

type Grant = {
  id: number
  player_id: number
  alias: string
  actor: string
  amount: number
  note: string
  created_at: string
}

/** The owner adds or takes back points for one player, with a reason the player sees. */
export function GrantsPanel({
  me,
  players,
  onGranted,
}: {
  me: number
  players: { id: number; alias: string; shared_keeper?: boolean }[]
  onGranted: () => void
}) {
  const [grants, setGrants] = useState<Grant[] | null>(null)
  const [playerId, setPlayerId] = useState('')
  const [amount, setAmount] = useState('')
  const [reason, setReason] = useState('')
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [busy, setBusy] = useState(false)

  const [requests, setRequests] = useState<PendingRequest[]>([])

  useEffect(() => {
    api<Grant[]>('/wallet/grants')
      .then(setGrants)
      .catch(() => setGrants([]))
    api<PendingRequest[]>('/wallet/requests')
      .then(setRequests)
      .catch(() => setRequests([]))
  }, [])

  async function decide(request: PendingRequest, approve: boolean) {
    setBusy(true)
    setError('')
    setNotice('')
    try {
      setRequests(
        await api<PendingRequest[]>(`/wallet/requests/${request.id}/decision`, 'POST', { approve }),
      )
      setNotice(
        approve
          ? `${request.alias}: +${points(request.amount)} очков`
          : `Запрос ${request.alias} отклонён`,
      )
      setGrants(await api<Grant[]>('/wallet/grants'))
      onGranted()
    } catch (e) {
      setError((e as Error).message)
      setRequests(await api<PendingRequest[]>('/wallet/requests').catch(() => requests))
    } finally {
      setBusy(false)
    }
  }

  const choices = players
    .filter((p) => p.id !== me && !p.shared_keeper)
    .sort((a, b) => a.alias.localeCompare(b.alias, 'ru'))
  const value = Number(amount.replace(',', '.'))
  const valid =
    playerId !== '' && Number.isFinite(value) && value !== 0 && reason.trim().length >= 3

  async function submit() {
    setBusy(true)
    setError('')
    setNotice('')
    try {
      const list = await api<Grant[]>('/wallet/grants', 'POST', {
        player_id: Number(playerId),
        amount: value,
        reason: reason.trim(),
      })
      setGrants(list)
      setNotice(`${list[0].alias}: ${value > 0 ? '+' : '−'}${points(Math.abs(value))} очков`)
      setAmount('')
      setReason('')
      onGranted()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="panel grants-panel" aria-label="Начисление очков">
      <h2 className="betting-section-title">Начисление очков</h2>
      <p className="muted caption">
        Только для владельца. Запросы игроков приходят и сюда, и в бот. Ниже — начисление
        вручную, для призов и исправлений: игрок увидит сумму и причину в своих операциях.
        Отрицательная сумма списывает очки. Очки не продаются за деньги.
      </p>
      {requests.length > 0 && (
        <ul className="point-requests" aria-label="Запросы очков">
          {requests.map((r) => (
            <li key={r.id}>
              <span>
                <strong>{r.alias}</strong> просит {points(r.amount)}
                <small className="muted"> · баланс {points(r.balance)}</small>
              </span>
              <span className="point-request-actions">
                <button
                  type="button"
                  className="button primary compact"
                  disabled={busy || r.player_id === me}
                  onClick={() => void decide(r, true)}
                >
                  Одобрить
                </button>
                <button
                  type="button"
                  className="button secondary compact"
                  disabled={busy || r.player_id === me}
                  onClick={() => void decide(r, false)}
                >
                  Отклонить
                </button>
              </span>
            </li>
          ))}
        </ul>
      )}
      <div className="grants-form">
        <label>
          Игрок
          <select value={playerId} onChange={(e) => setPlayerId(e.target.value)}>
            <option value="">Выберите игрока</option>
            {choices.map((p) => (
              <option key={p.id} value={p.id}>
                {p.alias}
              </option>
            ))}
          </select>
        </label>
        <label>
          Сумма
          <input
            inputMode="decimal"
            value={amount}
            placeholder="50"
            onChange={(e) => setAmount(e.target.value)}
          />
        </label>
        <label className="grants-reason">
          Причина
          <input
            value={reason}
            maxLength={200}
            placeholder="например, приз за лучший прогноз сезона"
            onChange={(e) => setReason(e.target.value)}
          />
        </label>
        <button
          type="button"
          className="button primary"
          disabled={!valid || busy}
          onClick={() => void submit()}
        >
          {value < 0 ? 'Списать' : 'Начислить'}
        </button>
      </div>
      {notice && (
        <p role="status" className="alert success">
          {notice}
        </p>
      )}
      {error && (
        <p role="alert" className="alert error">
          {error}
        </p>
      )}
      {grants && grants.length > 0 && (
        <details className="compact-explanation">
          <summary>Последние начисления</summary>
          <ul className="wallet-entries">
            {grants.map((g) => (
              <li key={g.id}>
                <span>
                  {g.alias} · {g.note}
                  <small className="muted"> ({g.actor})</small>
                </span>
                <span className="muted">
                  {new Date(g.created_at).toLocaleDateString('ru-RU', {
                    day: 'numeric',
                    month: 'short',
                    timeZone: 'Europe/Moscow',
                  })}
                </span>
                <span className={g.amount < 0 ? 'wallet-minus' : 'wallet-plus'}>
                  {g.amount > 0 ? '+' : '−'}
                  {points(Math.abs(g.amount))}
                </span>
              </li>
            ))}
          </ul>
        </details>
      )}
    </section>
  )
}
