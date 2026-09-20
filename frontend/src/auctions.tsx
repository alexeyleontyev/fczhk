import { useEffect, useState } from 'react'
import { api } from './api'
import type { Match, Run, Team } from './types'

type AuctionPlayer = { registration_id: number; player_id: number; alias: string }
type Lot = {
  id: string
  number: number
  round: number
  player: AuctionPlayer
  status: string
  winner: Team | null
  white_bid: number
  black_bid: number
}
type Auction = {
  id: number
  revision: number
  status: string
  side: Team | null
  budgets: Record<Team, number>
  limits: Record<Team, number>
  captains: Record<Team, number>
  participants: AuctionPlayer[]
  assignments: Record<string, Team>
  automatic: number[]
  current: {
    id: string
    number: number
    round: number
    player: AuctionPlayer
    own_bid: number | null
    submitted: Record<Team, boolean>
  } | null
  lots: Lot[]
}
const teamName = (t: Team) => (t === 'white' ? '⚪ Белые' : '⚫ Чёрные')
const states: Record<string, string> = {
  active: 'Торги идут',
  paused: 'Пауза',
  completed: 'Команды собраны',
  manual: 'Завершён вручную',
  cancelled: 'Отменён',
  invalidated: 'Состав изменился',
}

function AuctionHistory({ auction }: { auction: Auction }) {
  return (
    <div className="auction-history">
      {auction.lots.length === 0 && <p className="muted">Завершённых лотов пока нет.</p>}
      {[...auction.lots].reverse().map((lot) => (
        <div className="history-row" key={lot.id}>
          <strong>
            #{lot.number} · {lot.player.alias} · круг {lot.round}
          </strong>
          <p>
            Белые: {lot.white_bid} · Чёрные: {lot.black_bid}
          </p>
          <span>
            {lot.winner
              ? `${teamName(lot.winner)} получают игрока`
              : 'Равные ставки — перенос на следующий круг'}
          </span>
        </div>
      ))}
      {auction.automatic.length > 0 && (
        <p>
          Бесплатно после заполнения соперника:{' '}
          {auction.automatic
            .map((id) => auction.participants.find((p) => p.registration_id === id)?.alias)
            .join(', ')}
          .
        </p>
      )}
    </div>
  )
}

export function AuctionPanel({
  match: m,
  admin,
  busy,
  run,
}: {
  match: Match
  admin: boolean
  busy: boolean
  run: Run
}) {
  const [auction, setAuction] = useState<Auction | null>(null)
  const [error, setError] = useState('')
  const [loaded, setLoaded] = useState(false)
  const [history, setHistory] = useState<Auction[] | null>(null)
  useEffect(() => {
    let current = true,
      pending = false
    const load = async () => {
      if (pending) return
      pending = true
      try {
        const data = await api<Auction | null>(`/matches/${m.id}/auction`)
        if (current) {
          setAuction(data)
          setError('')
          setLoaded(true)
          if (data && data.status !== m.auction_status) void run(async () => {})
        }
      } catch (e) {
        if (current) setError((e as Error).message)
      } finally {
        pending = false
      }
    }
    void load()
    const timer = setInterval(() => void load(), 2000)
    return () => {
      current = false
      clearInterval(timer)
    }
  }, [m.id, m.version, m.auction_status])
  const active = auction && ['active', 'paused'].includes(auction.status)
  const captains = m.registrations.filter((r) => r.selected && r.position === 'field' && !r.guest)
  const fieldCount = m.registrations.filter((r) => r.selected && r.position === 'field').length
  const control = (action: string) =>
    run(async () => {
      if (auction)
        setAuction(
          await api<Auction>(`/matches/${m.id}/auction/control`, 'POST', {
            auction_id: auction.id,
            revision: auction.revision,
            action,
          }),
        )
    }, 'Состояние аукциона обновлено')
  if (!admin && loaded && !auction) return null
  return (
    <section className="panel auction-panel">
      <div className="section-title">
        <h2>Аукцион капитанов</h2>
        {auction && <span className="tag">{states[auction.status]}</span>}
      </div>
      {error && (
        <p className="alert error" role="alert">
          {error}
        </p>
      )}
      {!loaded && !error && <p>Загрузка аукциона…</p>}
      {auction && (
        <>
          <div className="actual-teams">
            {(['white', 'black'] as Team[]).map((t) => (
              <div key={t}>
                <h3>{teamName(t)}</h3>
                <p>
                  Капитан:{' '}
                  {auction.participants.find((p) => p.player_id === auction.captains[t])?.alias}
                </p>
                <p>
                  <strong>{auction.budgets[t]}</strong> баллов ·{' '}
                  {Object.values(auction.assignments).filter((v) => v === t).length} /{' '}
                  {auction.limits[t]} мест
                </p>
                {auction.participants
                  .filter((p) => auction.assignments[p.registration_id] === t)
                  .map((p) => (
                    <p key={p.registration_id}>{p.alias}</p>
                  ))}
              </div>
            ))}
          </div>
          {auction.current && (
            <div className="auction-current">
              <div className="eyebrow">
                ЛОТ {auction.current.number} · КРУГ {auction.current.round}
              </div>
              <h3>{auction.current.player.alias}</h3>
              <p className="muted">
                Белые: {auction.current.submitted.white ? 'ставка принята' : 'ожидаем ставку'} ·
                Чёрные: {auction.current.submitted.black ? 'ставка принята' : 'ожидаем ставку'}
              </p>
              {auction.side && <p>Вы — капитан команды {teamName(auction.side)}.</p>}
              {auction.current.own_bid !== null && (
                <p className="alert">Ваша ставка: {auction.current.own_bid}. Изменить её нельзя.</p>
              )}
              {auction.side && auction.status === 'active' && auction.current.own_bid === null && (
                <form
                  key={auction.current.id}
                  onSubmit={(e) => {
                    e.preventDefault()
                    const amount = Number(new FormData(e.currentTarget).get('amount'))
                    void run(
                      async () =>
                        setAuction(
                          await api<Auction>(`/matches/${m.id}/auction/bids`, 'POST', {
                            auction_id: auction.id,
                            lot_id: auction.current!.id,
                            amount,
                          }),
                        ),
                      'Ставка принята',
                    )
                  }}
                >
                  <label>
                    Ваша закрытая ставка
                    <input
                      name="amount"
                      type="number"
                      min={0}
                      max={auction.budgets[auction.side]}
                      step={1}
                      defaultValue={0}
                      required
                    />
                  </label>
                  <p className="muted caption">
                    От 0 до {auction.budgets[auction.side]}. После отправки ставка окончательна. Обе
                    суммы раскроются после второй ставки.
                  </p>
                  <button className="button" disabled={busy}>
                    Подтвердить ставку
                  </button>
                </form>
              )}
            </div>
          )}
          {auction.status === 'paused' && (
            <p className="alert">Торги приостановлены. Ставки и очередь сохранены.</p>
          )}
          {auction.status === 'invalidated' && (
            <p className="alert">
              Итоговый список изменился. Прежние ставки сохранены в истории; начните новый аукцион
              по актуальному составу.
            </p>
          )}
          {auction.status === 'manual' && (
            <p className="alert">
              Выигранные игроки перенесены в состав. Распределите оставшихся вручную, назначьте
              вратарей и утвердите команды.
            </p>
          )}
          {auction.status === 'completed' && (
            <p className="alert success">
              Полевые распределены. Администратор проверяет состав, назначает вратарей и утверждает
              команды.
            </p>
          )}
          {admin && active && (
            <div className="auction-controls">
              <div className="inline wrap">
                <button
                  className="button secondary compact"
                  disabled={busy}
                  onClick={() => void control(auction.status === 'active' ? 'pause' : 'resume')}
                >
                  {auction.status === 'active' ? 'Пауза' : 'Продолжить торги'}
                </button>
                <button
                  className="button ghost compact"
                  disabled={busy}
                  onClick={() => void control('cancel')}
                >
                  Отменить аукцион
                </button>
              </div>
              <p className="muted caption">
                Если капитан не отвечает или ничьи повторяются, можно закончить торги и распределить
                оставшихся вручную. Выигранные игроки и история сохранятся; незавершённые ставки не
                раскрываются.
              </p>
              <button
                className="button secondary"
                disabled={busy}
                onClick={() => void control('manual')}
              >
                Завершить торги вручную
              </button>
            </div>
          )}
          <details>
            <summary>История лотов ({auction.lots.length})</summary>
            <AuctionHistory auction={auction} />
          </details>
        </>
      )}
      {admin && loaded && !active && !m.result && ['finalized', 'approved'].includes(m.status) && (
        <details open={!auction}>
          <summary>{auction ? 'Начать новый аукцион' : 'Подготовить аукцион'}</summary>
          <p className="muted">
            По 100 баллов каждому капитану. Начало новых торгов сбросит текущее распределение и
            утверждение. История предыдущих торгов сохранится.
          </p>
          <form
            onSubmit={(e) => {
              e.preventDefault()
              const f = new FormData(e.currentTarget)
              void run(
                async () =>
                  setAuction(
                    await api<Auction>(`/matches/${m.id}/auction`, 'POST', {
                      version: m.version,
                      white_captain: Number(f.get('white')),
                      black_captain: Number(f.get('black')),
                      larger_team: f.get('larger') || null,
                    }),
                  ),
                'Аукцион начат',
              )
            }}
          >
            {(['white', 'black'] as Team[]).map((t) => (
              <label key={t}>
                Капитан: {teamName(t)}
                <select aria-label={`Капитан: ${teamName(t)}`} name={t} required defaultValue="">
                  <option value="">Выберите капитана</option>
                  {captains.map((r) => (
                    <option key={r.id} value={r.player_id}>
                      {r.alias}
                    </option>
                  ))}
                </select>
              </label>
            ))}
            {fieldCount % 2 === 1 && (
              <label>
                Дополнительное место
                <select name="larger" required defaultValue="">
                  <option value="">Выберите команду</option>
                  <option value="white">Белые</option>
                  <option value="black">Чёрные</option>
                </select>
              </label>
            )}
            <button className="button" disabled={busy || captains.length < 2}>
              Начать аукцион
            </button>
            {captains.length < 2 && (
              <p className="muted">Нужны два зарегистрированных полевых в финальном списке.</p>
            )}
          </form>
        </details>
      )}
      {auction && (
        <button
          className="button ghost compact"
          disabled={busy}
          onClick={() =>
            void run(async () =>
              setHistory(await api<Auction[]>(`/matches/${m.id}/auctions/history`)),
            )
          }
        >
          Предыдущие аукционы
        </button>
      )}
      {history
        ?.filter((a) => a.id !== auction?.id)
        .map((a) => (
          <details key={a.id}>
            <summary>
              Аукцион #{a.id} · {states[a.status]}
            </summary>
            <AuctionHistory auction={a} />
          </details>
        ))}
    </section>
  )
}
