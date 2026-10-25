import { useEffect, useState } from 'react'
import { SectionTabs } from './section-tabs'
import { ArrowUpRight, Check, MapPin, Plus, RefreshCw } from 'lucide-react'
import { api } from './api'
import { Button, Empty } from './ui'
import { date, time, money, status } from './format'
import { TemporaryRatings, score } from './ratings'
import { Roster } from './roster'
import { LineupEntry } from './team-board'
import { MatchResult } from './results'
import { AuctionEntry } from './auctions'
import { PredictionPanel } from './predictions'
import { CollectionCountdown } from './collection-countdown'
import { PaymentStatus } from './payment-status'
import { GameControls } from './game-controls'
import { ArchivedGameScreen, isArchivedMatch } from './archived-game-screen'
import type { Match, Player, Position, Run, History } from './types'

export function GameScreen({
  m,
  isAdmin,
  busy,
  run,
  refresh,
  setModal,
  action,
  players,
  setTab,
  setHistory,
  me,
  openAuction,
  openLineup,
  revision,
  focusPrediction = false,
}: {
  m: Match | null
  isAdmin: boolean
  busy: boolean
  run: Run
  refresh: () => Promise<void>
  setModal: (value: string | null) => void
  action: (name: string) => Promise<void>
  players: Player[]
  setTab: (value: string) => void
  setHistory: (value: History) => void
  me: Player
  openAuction: (matchId: number) => void
  openLineup: (matchId: number) => void
  revision: number
  focusPrediction?: boolean
}) {
  useEffect(() => {
    if (focusPrediction && ['finalized', 'approved'].includes(m?.status || '')) {
      const frame = requestAnimationFrame(() =>
        document.getElementById('prediction')?.scrollIntoView({ block: 'start' }),
      )
      return () => cancelAnimationFrame(frame)
    }
  }, [focusPrediction, m?.id, m?.status])
  const [section, setSection] = useState('overview')
  const activeSection =
    section === 'result' && !['approved', 'completed'].includes(m?.status || '')
      ? 'overview'
      : section
  const mine = m?.registrations.find((r) => r.player_id === me.id)
  const prediction = m && !['draft', 'cancelled'].includes(m.status) && (
    <PredictionPanel
      key={`predictions-${m.id}`}
      match={m}
      busy={busy}
      run={run}
      onStandings={() => setTab('predictions')}
    />
  )
  if (m && isArchivedMatch(m))
    return (
      <ArchivedGameScreen
        match={m}
        players={players}
        admin={isAdmin}
        busy={busy}
        run={run}
        revision={revision}
        openLineup={openLineup}
      />
    )
  return (
    <>
      <div className="page-heading">
        <div>
          <div className="eyebrow">НАШ КЛУБ · КАЖДУЮ ПЯТНИЦУ</div>
          <h1>
            Выходим на поле<span className="orange">.</span>
          </h1>
        </div>
        <div className="inline">
          <button
            className="icon-button"
            aria-label="Обновить игру"
            disabled={busy}
            onClick={() => void run(refresh)}
          >
            <RefreshCw size={18} />
          </button>
          {isAdmin && !m && (
            <Button className="secondary compact" onClick={() => setModal('create')}>
              <Plus size={17} /> Новая игра
            </Button>
          )}
        </div>
      </div>
      <CollectionCountdown refresh={refresh} currentGame={m} />
      {!m ? (
        <Empty
          title="Скоро новая игра"
          text="Когда администратор откроет сбор, здесь появится запись."
        />
      ) : (
        <>
          <section className="match-hero">
            <div className="hero-copy">
              <span className={`status-pill ${m.status}`}>
                <span />
                {status[m.status]}
              </span>
              <h2>
                {date(m.starts_at)}
                <span>
                  {m.historical ? (
                    'Время неизвестно'
                  ) : (
                    <>
                      {time(m.starts_at)} <small>МСК</small>
                    </>
                  )}
                </span>
              </h2>
              {!m.historical && (
                <>
                  <p>
                    <MapPin size={17} />
                    {m.location}
                  </p>
                  <div className="hero-bottom">
                    <span>
                      {money(m.cost)} <small>за игру</small>
                    </span>
                    <span>
                      8 + 1 <small>в команде</small>
                    </span>
                  </div>
                </>
              )}
            </div>
            <div className="pitch" aria-hidden="true">
              <div className="pitch-middle" />
              <div className="pitch-box left" />
              <div className="pitch-box right" />
              <span className="pitch-dot one" />
              <span className="pitch-dot two" />
              <span className="pitch-dot three" />
              <span className="pitch-dot four" />
              <span className="pitch-dot five" />
            </div>
          </section>
          {m.status === 'cancelled' && (
            <p className="alert" role="status">
              Игра отменена: {m.cancellation_reason || 'Обратитесь к организатору'}. История оплат
              сохранена. Возврат или перенос оплаты согласуйте с организатором.
            </p>
          )}
          <SectionTabs
            label="Разделы игры"
            value={activeSection}
            onChange={setSection}
            options={[
              { value: 'overview', label: 'Обзор' },
              ...(['approved', 'completed'].includes(m.status)
                ? [{ value: 'result', label: 'Итог' }]
                : []),
            ]}
          >
            <div hidden={activeSection !== 'overview'}>
              {isAdmin && (
                <GameControls
                  match={m}
                  busy={busy}
                  run={run}
                  action={action}
                  setModal={setModal}
                  setHistory={setHistory}
                  openLineup={openLineup}
                />
              )}
              {['finalized', 'approved'].includes(m.status) && (
                <div className="game-prediction-top" id="prediction">
                  {prediction}
                </div>
              )}
            </div>
            <div className="content-grid compact-game">
              <div className="primary-column">
                {!['finalized', 'approved'].includes(m.status) && prediction && (
                  <details
                    className="compact-explanation panel"
                    hidden={activeSection !== 'overview'}
                  >
                    <summary>Прогноз на игру</summary>
                    {prediction}
                  </details>
                )}
                {(m.auction_status ||
                  (!m.result && ['finalized', 'approved'].includes(m.status))) && (
                  <div hidden={activeSection !== 'overview'}>
                    <AuctionEntry
                      key={`auction-${m.id}`}
                      match={m}
                      admin={isAdmin}
                      busy={busy}
                      onOpen={() => openAuction(m.id)}
                      onStatusChange={() => void run(refresh)}
                    />
                  </div>
                )}
                {['approved', 'completed'].includes(m.status) && (
                  <div hidden={activeSection !== 'result'}>
                    <MatchResult
                      key={`result-${m.id}`}
                      match={m}
                      players={players}
                      admin={isAdmin}
                      busy={busy}
                      run={run}
                    />
                  </div>
                )}
                <section className="panel" hidden={activeSection !== 'overview'}>
                  <div className="section-title">
                    <h2>Сбор на игру</h2>
                    <span className="muted">{m.registrations.length} записались</span>
                  </div>
                  {['finalized', 'approved', 'completed'].includes(m.status) &&
                    m.team_ratings.strength && (
                      <div className="collection-strength">
                        <p>
                          <strong>Сила сбора: {score(m.team_ratings.strength.total)}</strong>
                          {m.team_ratings.strength.total === null && (
                            <> · известная сумма {score(m.team_ratings.strength.rated_total)}</>
                          )}
                        </p>
                        <p className="muted caption">
                          Полевые: атака + защита; вратари: защита. Оценены{' '}
                          {m.team_ratings.strength.rated} из {m.team_ratings.strength.count}{' '}
                          игроков.
                          {m.team_ratings.frozen ? ' Зафиксировано при утверждении.' : ''}
                        </p>
                      </div>
                    )}
                  <div className="counts">
                    {(['field', 'keeper'] as Position[]).map((pos) => {
                      const amount = m.registrations.filter(
                        (r) => (r.in_main ?? r.selected) && r.position === pos,
                      ).length
                      const limit = pos === 'field' ? m.field_limit : m.keeper_limit
                      return (
                        <div key={pos}>
                          <div>
                            <span>{pos === 'field' ? 'Полевые' : 'Вратари'}</span>
                            <strong>
                              {amount}
                              <small> / {limit}</small>
                            </strong>
                          </div>
                          <div className="meter">
                            <span style={{ width: `${Math.min(100, (amount / limit) * 100)}%` }} />
                          </div>
                        </div>
                      )
                    })}
                  </div>
                  <p className="muted caption">
                    {m.status === 'open'
                      ? 'В основном списке — первые записавшиеся полевые и вратари. При утверждении пройдут игроки с оплатой, подтверждённой администратором, по времени записи.'
                      : 'Самостоятельная запись закрыта. Изменения вносит администратор.'}
                  </p>
                  {m.status === 'open' && (
                    <div className="join-box">
                      {mine ? (
                        <>
                          <div>
                            <Check size={18} />
                            <strong>
                              Вы записаны {mine.position === 'field' ? 'полевым' : 'вратарем'}
                            </strong>
                          </div>
                          <PaymentStatus
                            reported={Boolean(mine.payment_reported)}
                            confirmed={mine.paid}
                            alias={me.alias}
                          />
                          <div className="inline wrap">
                            {!mine.paid && (
                              <Button
                                disabled={busy}
                                className="secondary compact"
                                onClick={() =>
                                  void run(
                                    () =>
                                      api(`/matches/${m.id}/payment-report`, 'PUT', {
                                        reported: !mine.payment_reported,
                                      }),
                                    mine.payment_reported
                                      ? 'Отметка об оплате отменена'
                                      : 'Об оплате сообщили. Ожидаем подтверждения администратора.',
                                  )
                                }
                              >
                                {mine.payment_reported ? 'Отменить отметку оплаты' : 'Я оплатил'}
                              </Button>
                            )}
                            <Button
                              disabled={busy}
                              className="secondary compact"
                              onClick={() =>
                                void run(
                                  () =>
                                    api(`/matches/${m.id}/join`, 'POST', {
                                      position: mine.position === 'field' ? 'keeper' : 'field',
                                    }),
                                  'Амплуа изменено. Время записи обновлено.',
                                )
                              }
                            >
                              Сменить амплуа
                            </Button>
                            <Button
                              disabled={busy}
                              className="ghost compact"
                              onClick={() => setModal('leave')}
                            >
                              Отменить запись
                            </Button>
                          </div>
                        </>
                      ) : (
                        <>
                          <strong>Будете играть?</strong>
                          <div className="inline wrap">
                            <Button
                              disabled={busy}
                              onClick={() =>
                                void run(
                                  () => api(`/matches/${m.id}/join`, 'POST', { position: 'field' }),
                                  'Вы записаны полевым',
                                )
                              }
                            >
                              Записаться полевым <ArrowUpRight size={17} />
                            </Button>
                            <Button
                              disabled={busy}
                              className="secondary"
                              onClick={() =>
                                void run(
                                  () =>
                                    api(`/matches/${m.id}/join`, 'POST', {
                                      position: 'keeper',
                                    }),
                                  'Вы записаны вратарем',
                                )
                              }
                            >
                              Записаться вратарем
                            </Button>
                          </div>
                        </>
                      )}
                    </div>
                  )}
                </section>
                {mine &&
                  m.status !== 'open' &&
                  !mine.paid &&
                  ['finalized', 'approved'].includes(m.status) && (
                    <section className="panel own-payment" hidden={activeSection !== 'overview'}>
                      <PaymentStatus
                        reported={Boolean(mine.payment_reported)}
                        confirmed={mine.paid}
                        alias={me.alias}
                      />
                      <Button
                        disabled={busy}
                        onClick={() =>
                          void run(() =>
                            api(`/matches/${m.id}/payment-report`, 'PUT', {
                              reported: !mine.payment_reported,
                            }),
                          )
                        }
                      >
                        {mine.payment_reported ? 'Отменить отметку оплаты' : 'Я оплатил'}
                      </Button>
                    </section>
                  )}
                <section className="panel" hidden={activeSection !== 'overview'}>
                  <div className="section-title">
                    <h2>Участники</h2>
                    {isAdmin && !m.result && m.status !== 'cancelled' && (
                      <Button
                        disabled={busy}
                        className="secondary compact"
                        onClick={() => setModal('include')}
                      >
                        <Plus size={16} /> Добавить игрока
                      </Button>
                    )}
                  </div>
                  <Roster
                    match={m}
                    admin={isAdmin && !m.result && m.status !== 'cancelled'}
                    busy={busy}
                    run={run}
                  />
                  {isAdmin && !m.result && m.status !== 'cancelled' && (
                    <TemporaryRatings key={m.id} match={m} busy={busy} run={run} />
                  )}
                </section>
                {activeSection === 'overview' && m.status !== 'draft' && (
                  <LineupEntry match={m} onOpen={() => openLineup(m.id)} />
                )}
              </div>
              <aside>
                <details
                  className="panel info-panel compact-explanation"
                  hidden={activeSection !== 'overview'}
                >
                  <summary>Информация и оплата</summary>
                  <div className="eyebrow">ПЕРЕД ИГРОЙ</div>
                  <h2>Всё, что нужно знать</h2>
                  <p className="preline">
                    {m.description || 'Дополнительной информации пока нет.'}
                  </p>
                  <div className="divider" />
                  <h3>Оплата</h3>
                  <p className="preline">
                    {m.payment_details || 'Реквизиты уточняйте у администратора.'}
                  </p>
                  <span className="muted caption">
                    Отметка оплаты появляется после подтверждения администратором.
                  </span>
                </details>
              </aside>
            </div>
          </SectionTabs>
        </>
      )}
    </>
  )
}
