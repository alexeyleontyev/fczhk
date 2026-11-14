import { useEffect, useRef, useState } from 'react'
import { Check, ChevronDown, X } from 'lucide-react'

import { ApiError, api } from './api'
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
      model?: { n_matches: number; fitted_at: string }
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
  version,
  refresh,
  title,
  balance,
  onPlaced,
}: {
  matchId: number
  // The match version changes with every approval and colour swap; the line follows it.
  version: number
  // Bumped by the screen's «Обновить» button.
  refresh: number
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
  const held = useRef<MatchOdds | null>(null)

  useEffect(() => {
    let active = true
    api<MatchOdds>(`/matches/${matchId}/odds`)
      .then((data) => {
        if (!active) return
        const previous = held.current
        if (previous?.available && (!data.available || previous.odds_id !== data.odds_id)) {
          // A new approval brings a new line: keep only selections it still offers.
          const offered = new Set(
            data.available ? data.groups.flatMap((g) => g.selections.map((s) => s.id)) : [],
          )
          setPicked((current) => current.filter((id) => offered.has(id)))
          setNotice('Составы изменились — линия обновлена. Проверьте купон.')
        }
        held.current = data
        setLine(data)
      })
      .catch((e) => {
        if (active) setError((e as Error).message)
      })
    return () => {
      active = false
    }
  }, [matchId, version, refresh, revision])

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
        if (!active) return
        // 409: the line this screen holds is no longer current; fetch the new one.
        if (e instanceof ApiError && e.status === 409) setRevision((value) => value + 1)
        else setError((e as Error).message)
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
      // Shown even when the line reloads: a changed price or line must not pass silently.
      setError((e as Error).message)
      if (e instanceof ApiError && e.status === 409) setRevision((value) => value + 1)
    } finally {
      setBusy(false)
    }
  }

  if (!line) return null
  const labels = new Map(
    line.available ? line.groups.flatMap((g) => g.selections.map((s) => [s.id, s.label])) : [],
  )
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
              ? 'Приём ставок до начала игры. Коэффициенты рассчитаны по утверждённым составам и не меняются.'
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
                {picked
                  .map((id) => labels.get(id) ?? id)
                  .map((text, i) => (
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

type ArchiveEntry = {
  match_id: number
  starts_at: string
  score: { white: number; black: number } | null
  bets: number
  players: number
  staked: number
  returned: number
  open: number
  bank: number | null
}
type PlayerBet = Bet & { player_id: number; alias: string }

const plural = (n: number, one: string, few: string, many: string) => {
  const d = n % 10
  const h = n % 100
  const word = d === 1 && h !== 11 ? one : d >= 2 && d <= 4 && (h < 12 || h > 14) ? few : many
  return `${n} ${word}`
}
const day = (iso: string) =>
  new Date(iso).toLocaleDateString('ru-RU', {
    day: 'numeric',
    month: 'long',
    year: 'numeric',
    timeZone: 'Europe/Moscow',
  })

function ArchiveMatch({ entry, me }: { entry: ArchiveEntry; me: number }) {
  const [rows, setRows] = useState<PlayerBet[] | null>(null)
  const [error, setError] = useState('')
  function load() {
    if (rows) return
    api<PlayerBet[]>(`/matches/${entry.match_id}/bets`)
      .then(setRows)
      .catch((e) => setError((e as Error).message))
  }
  return (
    <details className="bets-archive-match" onToggle={(e) => e.currentTarget.open && load()}>
      <summary>
        <span>
          <strong>{day(entry.starts_at)}</strong>
          {entry.score && ` · ${entry.score.white}:${entry.score.black}`}
        </span>
        <small className="muted">
          {plural(entry.bets, 'ставка', 'ставки', 'ставок')} ·{' '}
          {plural(entry.players, 'игрок', 'игрока', 'игроков')} ·{' '}
          {entry.bank === null
            ? 'идёт расчёт'
            : `банк ${entry.bank > 0 ? '+' : entry.bank < 0 ? '−' : ''}${points(Math.abs(entry.bank))}`}
        </small>
      </summary>
      {error && <p className="alert error">{error}</p>}
      {rows && (
        <ul className="my-bets">
          {rows.map((b) => (
            <li key={b.id} className={`bet-${b.status} ${b.player_id === me ? 'mine' : ''}`}>
              <div>
                <span>
                  <strong>{b.alias}</strong>
                  {b.player_id === me ? ' · вы' : ''}: {b.labels.join(' + ')}
                </span>
                <small className="muted">
                  {points(b.stake)} × {odd(b.odds)}
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
      )}
    </details>
  )
}

export function BetsArchive({ me, revision }: { me: number; revision: number }) {
  const [entries, setEntries] = useState<ArchiveEntry[] | null>(null)
  useEffect(() => {
    let active = true
    api<ArchiveEntry[]>('/betting/archive')
      .then((data) => {
        if (active) setEntries(data)
      })
      .catch(() => {
        if (active) setEntries([])
      })
    return () => {
      active = false
    }
  }, [revision])
  if (!entries || entries.length === 0) return null
  return (
    <section className="panel" aria-label="Архив ставок">
      <h2 className="betting-section-title">Архив ставок</h2>
      <p className="muted caption">
        Ставки всех игроков открываются в момент начала игры. Нажмите на игру, чтобы увидеть, кто на
        что ставил.
      </p>
      {entries.map((entry) => (
        <ArchiveMatch key={entry.match_id} entry={entry} me={me} />
      ))}
    </section>
  )
}
