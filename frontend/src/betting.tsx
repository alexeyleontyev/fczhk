import { useEffect, useState } from 'react'
import { Gift, Landmark } from 'lucide-react'

import { api } from './api'
import { BetsArchive, MatchLine, MyBets } from './bet-slip'
import './betting.css'

type WalletEntryKind = 'freebet' | 'stake' | 'payout' | 'refund' | 'correction'

export type Wallet = {
  server_time: string
  balance: number
  profit: number
  freebets: number
  freebet: { amount: number; week: string; available: boolean; next_at: string }
  entries: {
    id: number
    kind: WalletEntryKind
    amount: number
    week: string | null
    created_at: string
  }[]
}

export type BettingLeaderboard = {
  rows: {
    rank: number
    player_id: number
    alias: string
    balance: number
    freebets: number
    profit: number
    staked: number
  }[]
  bank: { balance: number; in_play: number; staked: number; paid_out: number; refunded: number }
  freebets_issued: number
  players: number
}

const KIND_LABEL: Record<WalletEntryKind, string> = {
  freebet: 'Фрибет',
  stake: 'Ставка',
  payout: 'Выигрыш',
  refund: 'Возврат',
  correction: 'Перерасчёт',
}

export const points = (n: number) => n.toLocaleString('ru-RU', { maximumFractionDigits: 2 })
const signed = (n: number) => (n > 0 ? '+' : n < 0 ? '−' : '') + points(Math.abs(n))
const moscowDay = (iso: string) =>
  new Date(iso).toLocaleDateString('ru-RU', {
    weekday: 'long',
    day: 'numeric',
    month: 'long',
    timeZone: 'Europe/Moscow',
  })
const moscowStamp = (iso: string) =>
  new Date(iso).toLocaleString('ru-RU', {
    day: 'numeric',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
    timeZone: 'Europe/Moscow',
  })

export function BettingScreen({
  me,
  onPlayer,
  match,
}: {
  me: number
  onPlayer: (id: number) => void
  match?: { id: number; status: string; starts_at: string } | null
}) {
  const [wallet, setWallet] = useState<Wallet | null>(null)
  const [board, setBoard] = useState<BettingLeaderboard | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [revision, setRevision] = useState(0)

  useEffect(() => {
    let active = true
    setBusy(true)
    setError('')
    Promise.all([api<Wallet>('/wallet'), api<BettingLeaderboard>('/betting/leaderboard')])
      .then(([w, b]) => {
        if (!active) return
        setWallet(w)
        setBoard(b)
      })
      .catch((e) => {
        if (active) setError((e as Error).message)
      })
      .finally(() => {
        if (active) setBusy(false)
      })
    return () => {
      active = false
    }
  }, [revision])

  async function claim() {
    setBusy(true)
    setError('')
    try {
      setWallet(await api<Wallet>('/wallet/freebet', 'POST'))
      setBoard(await api<BettingLeaderboard>('/betting/leaderboard'))
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const bank = board?.bank
  return (
    <>
      <div className="page-heading">
        <div>
          <div className="eyebrow">ВИРТУАЛЬНЫЕ ОЧКИ</div>
          <h1>Ставки</h1>
          <h2 className="folio-meta">Баланс, фрибеты и общий зачёт</h2>
        </div>
        <button
          className="button secondary compact"
          disabled={busy}
          onClick={() => setRevision((value) => value + 1)}
        >
          Обновить
        </button>
      </div>
      {error && (
        <p role="alert" className="alert error">
          {error}
        </p>
      )}
      {wallet && (
        <section className="panel wallet-panel" aria-label="Мой баланс">
          <div className="wallet-balance">
            <span className="wallet-label">Мой баланс</span>
            <strong>{points(wallet.balance)}</strong>
            <span className="wallet-meta">
              Фрибетов получено: {points(wallet.freebets)} · результат ставок:{' '}
              <span className={wallet.profit < 0 ? 'wallet-minus' : 'wallet-plus'}>
                {signed(wallet.profit)}
              </span>
            </span>
          </div>
          <div className="wallet-freebet">
            {wallet.freebet.available ? (
              <button className="button primary" disabled={busy} onClick={() => void claim()}>
                <Gift size={16} /> Забрать фрибет +{wallet.freebet.amount}
              </button>
            ) : (
              <p className="wallet-next">
                Фрибет этой недели получен. Следующий — {moscowDay(wallet.freebet.next_at)}.
              </p>
            )}
            <p className="muted caption">
              Раз в неделю, с понедельника по московскому времени. Неполученный фрибет не копится.
            </p>
          </div>
        </section>
      )}
      {wallet && match && ['approved', 'completed'].includes(match.status) && (
        <MatchLine
          matchId={match.id}
          title={new Date(match.starts_at).toLocaleDateString('ru-RU', {
            day: 'numeric',
            month: 'long',
            timeZone: 'Europe/Moscow',
          })}
          balance={wallet.balance}
          onPlaced={() => setRevision((value) => value + 1)}
        />
      )}
      <MyBets revision={revision} />
      <BetsArchive me={me} revision={revision} />
      {bank && (
        <section className="panel bank-panel" aria-label="Банк">
          <Landmark size={18} aria-hidden="true" />
          <div>
            <span className="wallet-label">Банк</span>
            <strong className={bank.balance < 0 ? 'wallet-minus' : ''}>
              {signed(bank.balance)}
            </strong>
            <p className="wallet-meta">
              {bank.balance >= 0
                ? 'Столько игроки суммарно проиграли банку по рассчитанным ставкам.'
                : 'Игроки в сумме обыграли банк на столько.'}{' '}
              {bank.in_play > 0 && `Ещё ${points(bank.in_play)} в игре. `}
              Принято ставок {points(bank.staked)}, выплачено {points(bank.paid_out)}, возвращено{' '}
              {points(bank.refunded)}.
            </p>
          </div>
        </section>
      )}
      {board && (
        <section className="panel standings-panel" aria-label="Лидерборд">
          <h2 className="betting-section-title">Лидерборд</h2>
          {board.rows.length === 0 ? (
            <p className="empty-small">Пока ни у кого нет очков. Заберите первый фрибет.</p>
          ) : (
            <div className="table-scroll" role="region" aria-label="Таблица балансов" tabIndex={0}>
              <table className="standings-table betting-standings">
                <thead>
                  <tr>
                    <th aria-label="Место" title="Место">
                      №
                    </th>
                    <th>Игрок</th>
                    <th title="Текущий баланс">Баланс</th>
                    <th title="Баланс минус полученные фрибеты">Результат</th>
                  </tr>
                </thead>
                <tbody>
                  {board.rows.map((row) => (
                    <tr key={row.player_id} className={row.player_id === me ? 'mine' : ''}>
                      <td>{row.rank}</td>
                      <td>
                        <button className="text-button" onClick={() => onPlayer(row.player_id)}>
                          {row.alias}
                          {row.player_id === me ? ' · вы' : ''}
                        </button>
                      </td>
                      <td className="betting-number">{points(row.balance)}</td>
                      <td
                        className={`betting-number ${row.profit < 0 ? 'wallet-minus' : 'wallet-plus'}`}
                      >
                        {signed(row.profit)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <p className="muted caption">
            Участников: {board.players}. Выдано фрибетов: {points(board.freebets_issued)}. При
            равном балансе место общее.
          </p>
        </section>
      )}
      {wallet && wallet.entries.length > 0 && (
        <section className="panel" aria-label="Мои операции">
          <details className="compact-explanation">
            <summary>Мои операции</summary>
            <ul className="wallet-entries">
              {wallet.entries.map((e) => (
                <li key={e.id}>
                  <span>{KIND_LABEL[e.kind]}</span>
                  <span className="muted">{moscowStamp(e.created_at)}</span>
                  <span className={e.amount < 0 ? 'wallet-minus' : 'wallet-plus'}>
                    {signed(e.amount)}
                  </span>
                </li>
              ))}
            </ul>
          </details>
        </section>
      )}
    </>
  )
}
