import { useEffect, useState } from 'react'
import { Check, ChevronDown, X } from 'lucide-react'

import { api } from './api'
import { points } from './betting'

export type Selection = { id: string; label: string; odds: number }

export type MatchOdds =
  | { available: false; reason: string; bets: Bet[] }
  | {
      available: true
      odds_id: number
      match_id: number
      approved_version: number
      open: boolean
      closes_at: string
      model: { n_matches: number; fitted_at: string }
      groups: { name: string; selections: Selection[] }[]
      bets: Bet[]
    }

export type Bet = {
  id: number
  match_id: number
  selections: string[]
  labels: string[]
  stake: number
  odds: number
  potential: number
  status: 'open' | 'won' | 'lost' | 'void'
  credited: number
  outcome: { reason?: string; score?: { white: number; black: number } } | null
  created_at: string
  settled_at: string | null
}

type Quote = { odds_id: number; selections: string[]; labels: string[]; odds: number }

const STATUS: Record<Bet['status'], string> = {
  open: 'В игре',
  won: 'Выигрыш',
  lost: 'Проигрыш',
  void: 'Возврат',
}
const odd = (n: number) => n.toLocaleString('ru-RU', { minimumFractionDigits: 2 })
// Open by default: the outcome and match total; the long lists stay folded.
const OPEN_GROUPS = ['Исход', 'Тотал матча']

export function MatchLine({
  matchId,
  title,
  balance,
  onPlaced,
}: {
  matchId: number
  title: string
  balance: number
  onPlaced: () => void
}) {
  const [line, setLine] = useState<MatchOdds | null>(null)
  const [picked, setPicked] = useState<string[]>([])
  const [quote, setQuote] = useState<Quote | null>(null)
  const [stake, setStake] = useState('10')
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [busy, setBusy] = useState(false)
  const [revision, setRevision] = useState(0)

  useEffect(() => {
    let active = true
    api<MatchOdds>(`/matches/${matchId}/odds`)
      .then((data) => {
        if (active) setLine(data)
      })
      .catch((e) => {
        if (active) setError((e as Error).message)
      })
    return () => {
      active = false
    }
  }, [matchId, revision])

  const oddsId = line?.available ? line.odds_id : null
  useEffect(() => {
    setQuote(null)
    if (!oddsId || picked.length === 0) return
    let active = true
    api<Quote>(`/matches/${matchId}/odds/quote`, 'POST', { odds_id: oddsId, selections: picked })
      .then((q) => {
        if (active) {
          setQuote(q)
          setError('')
        }
      })
      .catch((e) => {
        if (active) setError((e as Error).message)
      })
    return () => {
      active = false
    }
  }, [matchId, oddsId, picked])

  function toggle(id: string) {
    setNotice('')
    setPicked((current) =>
      current.includes(id) ? current.filter((s) => s !== id) : [...current, id],
    )
  }

  async function place() {
    if (!quote || !oddsId) return
    setBusy(true)
    setError('')
    try {
      await api(`/matches/${matchId}/bets`, 'POST', {
        odds_id: oddsId,
        selections: picked,
        stake: Number(stake.replace(',', '.')),
        odds: quote.odds,
      })
      setNotice(`Ставка принята: ${quote.labels.join(' + ')} · коэффициент ${odd(quote.odds)}`)
      setPicked([])
      setRevision((value) => value + 1)
      onPlaced()
    } catch (e) {
      setError((e as Error).message)
      setRevision((value) => value + 1)
    } finally {
      setBusy(false)
    }
  }

  if (!line) return null
  const amount = Number(stake.replace(',', '.'))
  const valid = Number.isFinite(amount) && amount >= 1 && amount <= balance
  return (
    <section className="panel match-line" aria-label="Линия на игру">
      <h2 className="betting-section-title">Линия: {title}</h2>
      {!line.available ? (
        <p className="empty-small">{line.reason}</p>
      ) : (
        <>
          <p className="muted caption">
            {line.open
              ? `Приём ставок до начала игры. Коэффициенты рассчитаны по утверждённым составам и не меняются; модель обучена на ${line.model.n_matches} матчах.`
              : 'Приём ставок на эту игру закрыт.'}
          </p>
          {line.groups.map((group) => (
            <details
              key={group.name}
              className="odds-group"
              open={OPEN_GROUPS.includes(group.name) || undefined}
            >
              <summary>
                {group.name} <ChevronDown size={14} aria-hidden="true" />
              </summary>
              <div className="odds-grid">
                {group.selections.map((s) => (
                  <button
                    key={s.id}
                    type="button"
                    className={`odds-button ${picked.includes(s.id) ? 'picked' : ''}`}
                    aria-pressed={picked.includes(s.id)}
                    disabled={!line.open || busy}
                    onClick={() => toggle(s.id)}
                  >
                    <span>{s.label}</span>
                    <strong>{odd(s.odds)}</strong>
                  </button>
                ))}
              </div>
            </details>
          ))}
          {picked.length > 0 && line.open && (
            <div className="bet-slip" role="region" aria-label="Купон">
              <div className="bet-slip-head">
                <strong>
                  {picked.length === 1 ? 'Одиночная ставка' : `Комбо из ${picked.length}`}
                </strong>
                <button type="button" className="text-button" onClick={() => setPicked([])}>
                  <X size={14} /> Очистить
                </button>
              </div>
              <ul>
                {(quote?.labels ?? picked).map((text, i) => (
                  <li key={picked[i]}>
                    <span>{text}</span>
                    <button
                      type="button"
                      className="text-button"
                      aria-label={`Убрать: ${text}`}
                      onClick={() => toggle(picked[i])}
                    >
                      <X size={14} />
                    </button>
                  </li>
                ))}
              </ul>
              <label className="bet-stake">
                Сумма
                <input
                  inputMode="decimal"
                  value={stake}
                  onChange={(e) => setStake(e.target.value)}
                  aria-label="Сумма ставки"
                />
              </label>
              <p className="bet-total">
                Коэффициент <strong>{quote ? odd(quote.odds) : '…'}</strong>
                {quote && valid && (
                  <>
                    {' '}
                    · выигрыш <strong>{points(Math.round(amount * quote.odds * 100) / 100)}</strong>
                  </>
                )}
              </p>
              {picked.length > 1 && (
                <p className="muted caption">
                  Комбо считается по совместной вероятности исходов. Если исход на игрока не
                  состоялся (не вышел, гол без автора), вся ставка возвращается.
                </p>
              )}
              <button
                type="button"
                className="button primary bet-place"
                disabled={!quote || !valid || busy}
                onClick={() => void place()}
              >
                <Check size={16} /> Поставить {valid ? points(amount) : ''}
              </button>
              {!valid && <p className="muted caption">Сумма от 1 до {points(balance)}.</p>}
            </div>
          )}
          {notice && (
            <p role="status" className="alert success">
              {notice}
            </p>
          )}
        </>
      )}
      {error && (
        <p role="alert" className="alert error">
          {error}
        </p>
      )}
    </section>
  )
}

export function MyBets({ revision }: { revision: number }) {
  const [bets, setBets] = useState<Bet[] | null>(null)
  useEffect(() => {
    let active = true
    api<Bet[]>('/bets')
      .then((data) => {
        if (active) setBets(data)
      })
      .catch(() => {
        if (active) setBets([])
      })
    return () => {
      active = false
    }
  }, [revision])
  if (!bets || bets.length === 0) return null
  return (
    <section className="panel" aria-label="Мои ставки">
      <h2 className="betting-section-title">Мои ставки</h2>
      <ul className="my-bets">
        {bets.map((b) => (
          <li key={b.id} className={`bet-${b.status}`}>
            <div>
              <span>{b.labels.join(' + ')}</span>
              <small className="muted">
                {points(b.stake)} × {odd(b.odds)}
                {b.outcome?.score && ` · счёт ${b.outcome.score.white}:${b.outcome.score.black}`}
                {b.status === 'void' && b.outcome?.reason && ` · ${b.outcome.reason}`}
              </small>
            </div>
            <div className="bet-result">
              <span className="bet-status">{STATUS[b.status]}</span>
              <strong>{b.status === 'open' ? points(b.potential) : points(b.credited)}</strong>
            </div>
          </li>
        ))}
      </ul>
    </section>
  )
}
