import { useEffect, useState, type ReactNode } from 'react'
import { useLastCompleted } from './use-last-completed'
import { SectionTabs } from './section-tabs'
import { ArrowUpRight, Check, Plus, RefreshCw } from 'lucide-react'
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
import { CollectionImageEditor } from './collection-image'
import { ArchivedGameScreen, isArchivedMatch } from './archived-game-screen'
import type { Match, Player, Position, Run, History } from './types'

function PreviousGameRow({ revision, open }: { revision: number; open: (id: number) => void }) {
  const { match } = useLastCompleted(revision)
  if (!match?.result) return null
  return <button className="previous-row" onClick={() => open(match.id)}>
    <span><strong>Прошлая игра</strong><small>{date(match.starts_at)} · Белые — Чёрные</small></span>
    <b>{match.result.score.white} : {match.result.score.black} ›</b>
  </button>
}

export function GameScreen({
  m,
  matchTabs,
  openPrevious,
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
  saveImage,
  removeImage,
}: {
  m: Match | null
  matchTabs: ReactNode
  openPrevious: (id: number) => void
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
  saveImage: (file: File) => Promise<boolean>
  removeImage: () => void
}) {
  useEffect(() => {
    if (focusPrediction && ['finalized', 'approved'].includes(m?.status || '')) {
      const frame = requestAnimationFrame(() =>
        document.getElementById('prediction')?.scrollIntoView({ block: 'start' }),
      )
      return () => cancelAnimationFrame(frame)
    }
  }, [focusPrediction, m?.id, m?.status])
  const [section, setSection] = useState(() => new URLSearchParams(location.search).get('section') === 'result' ? 'result' : 'overview')
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
  const poster = m && activeSection === 'overview' && !focusPrediction && ['open', 'draft'].includes(m.status)
  const registrationPanel = m && (
<section className={`panel game-registration ${poster ? 'posterbody' : ''}`} hidden={activeSection !== 'overview'}>
                  <div className="section-title">
                    <h2>
                      {m.status === 'draft' && (m.scheduled_opening_at || m.collection_paused)
                        ? 'Предварительная запись'
                        : 'Сбор на игру'}
                    </h2>
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
                          {m.team_ratings.strength.with_keepers && (
                            <>
                              {' '}
                              (с вратарями:{' '}
                              {m.team_ratings.strength.with_keepers.total === null
                                ? `неполная, известная сумма ${score(m.team_ratings.strength.with_keepers.rated_total)}`
                                : score(m.team_ratings.strength.with_keepers.total)}
                              )
                            </>
                          )}
                        </p>
                        <p className="muted caption">
                          Только полевые: атака + защита. Оценены {m.team_ratings.strength.rated} из{' '}
                          {m.team_ratings.strength.count} полевых. В скобках — с защитой вратарей.
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
                          <div className="slots" aria-hidden="true">
                            {Array.from({ length: limit }, (_, i) => <i key={i} className={i < amount ? 'occupied' : undefined} />)}
                          </div>
                        </div>
                      )
                    })}
                  </div>
                  <details className="registration-help"><summary>Порядок записи и оплаты</summary>
                  <p className="muted caption">
                    {m.status === 'draft' && (m.scheduled_opening_at || m.collection_paused)
                      ? 'Этот список виден только администраторам. При открытии сбора игроки займут первые места в очереди. Оплату подтверждает администратор.'
                      : m.status === 'open'
                        ? 'В основном списке — первые записавшиеся полевые и вратари. При утверждении пройдут игроки с оплатой, подтверждённой администратором, по времени записи.'
                        : 'Самостоятельная запись закрыта. Изменения вносит администратор.'}
                  </p>
                  </details>
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
                              onClick={() => {
                                if (
                                  !window.confirm(
                                    'Вы точно хотите сменить амплуа? Время записи обновится, и вы займёте новое место в очереди.',
                                  )
                                )
                                  return
                                void run(
                                  () =>
                                    api(`/matches/${m.id}/join`, 'POST', {
                                      position: mine.position === 'field' ? 'keeper' : 'field',
                                    }),
                                  'Амплуа изменено. Время записи обновлено.',
                                )
                              }}
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
  )
  return (
    <>
      <div className={m ? "game-refresh" : "page-heading"}>
        <div>
          <div className="eyebrow">НАШ КЛУБ · КАЖДУЮ ПЯТНИЦУ</div>
          {!m && <h1>Выходим на поле.</h1>}
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
          <section className={`match-hero ${activeSection === 'result' || focusPrediction || !['open', 'draft'].includes(m.status) ? 'protocol-match' : ''}`} aria-label="Карточка матча">
            <img className="poster-crest" src="/assets/club/crest.webp" alt="" />
            <div className="hero-copy">
              <h1 className="poster-kicker" aria-label="Выходим на поле.">{poster ? 'Следующая игра' : 'Игра клуба'}</h1>
              <span className={`status-pill ${m.status}`}>
                <span />
                {m.status === 'draft' && (m.scheduled_opening_at || m.collection_paused)
                  ? 'Запланирована'
                  : status[m.status]}
              </span>
              <h2>
                <strong className="poster-date">{date(m.starts_at).split(' ').map((part) => <span key={part}>{part}</span>)}</strong>
              </h2>
              <p className="poster-when">
                <span>{m.historical ? 'Время неизвестно' : new Intl.DateTimeFormat('ru-RU', {weekday:'short', timeZone:'Europe/Moscow'}).format(new Date(m.starts_at))+' · '+time(m.starts_at)}</span>
                {!m.historical && <span>{m.location}</span>}
              </p>
              {!m.historical && (
                <>
                  <div className="hero-bottom">
                    <span>
                      {money(m.cost)} <small>за игру</small>
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
          {m.status !== 'open' && matchTabs}
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
            {m.status === 'open' && <>{registrationPanel}{matchTabs}<PreviousGameRow revision={revision} open={openPrevious} /></>}
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
              {isAdmin && m.status === 'draft' && (
                <section className="panel">
                  <CollectionImageEditor
                    match={m}
                    busy={busy}
                    save={saveImage}
                    remove={removeImage}
                  />
                </section>
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
                {m.status !== 'open' && registrationPanel}
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
