import { useState } from 'react'
import { SectionTabs } from './section-tabs'
import { ArrowUpRight, Check, Flag, MapPin, Plus, RefreshCw, Shield } from 'lucide-react'
import { api } from './api'
import { Button, Empty } from './ui'
import { date, time, money, status } from './format'
import { TemporaryRatings, score } from './ratings'
import { Roster } from './roster'
import { LineupEntry } from './team-board'
import { MatchResult } from './results'
import { AuctionEntry } from './auctions'
import { PredictionPanel } from './predictions'
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
}) {
  const [section, setSection] = useState('overview')
  const activeSection =
    (section === 'manage' && !isAdmin) ||
    (section === 'result' && !['approved', 'completed'].includes(m?.status || ''))
      ? 'overview'
      : section
  const auctionRunning = ['active', 'paused'].includes(m?.auction_status || '')
  const mine = m?.registrations.find((r) => r.player_id === me.id)
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
          {isAdmin && (
            <Button className="secondary compact" onClick={() => setModal('create')}>
              <Plus size={17} /> Новая игра
            </Button>
          )}
        </div>
      </div>
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
          {isAdmin &&
            activeSection !== 'manage' &&
            m.publications.some((p) => ['failed', 'uncertain'].includes(p.status) && !p.stale) && (
              <div className="alert error" role="alert">
                <span>Есть сообщения, требующие проверки.</span>
                <button onClick={() => setSection('manage')}>Проверить публикации</button>
              </div>
            )}
          <SectionTabs
            label="Разделы игры"
            value={activeSection}
            onChange={setSection}
            options={[
              { value: 'overview', label: 'Обзор' },
              { value: 'roster', label: 'Участники' },
              ...(['approved', 'completed'].includes(m.status)
                ? [{ value: 'result', label: 'Итог' }]
                : []),
              ...(isAdmin ? [{ value: 'manage', label: 'Управление' }] : []),
            ]}
          >
            <div className="content-grid compact-game">
              <div className="primary-column">
                {!['draft', 'cancelled'].includes(m.status) && (
                  <details
                    className="compact-explanation panel"
                    hidden={activeSection !== 'overview'}
                  >
                    <summary>Прогноз на игру</summary>
                    <PredictionPanel
                      key={`predictions-${m.id}`}
                      match={m}
                      busy={busy}
                      run={run}
                      onStandings={() => setTab('predictions')}
                    />
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
                  {isAdmin && (
                    <div className="inline wrap game-next-action">
                      {m.status === 'draft' && (
                        <Button disabled={busy} onClick={() => void action('open')}>
                          Открыть сбор
                        </Button>
                      )}
                      {m.status === 'open' && (
                        <Button disabled={busy} onClick={() => setModal('finalize')}>
                          Финализировать сбор <Flag size={16} />
                        </Button>
                      )}
                      {m.status === 'approved' && (
                        <Button disabled={busy} onClick={() => void action('publish')}>
                          Опубликовать составы <ArrowUpRight size={16} />
                        </Button>
                      )}
                    </div>
                  )}
                  <div className="counts">
                    {(['field', 'keeper'] as Position[]).map((pos) => {
                      const amount = m.registrations.filter(
                        (r) => r.selected && r.position === pos,
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
                      ? 'Место определяется временем записи среди оплативших. До финализации список предварительный.'
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
                          <p>
                            {mine.paid
                              ? 'Оплата подтверждена'
                              : 'Оплату подтвердит администратор после перевода'}
                          </p>
                          <div className="inline">
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
                          <div className="inline">
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
                              Я вратарь
                            </Button>
                          </div>
                        </>
                      )}
                    </div>
                  )}
                </section>
                <section className="panel" hidden={activeSection !== 'roster'}>
                  <div className="section-title">
                    <h2>Участники</h2>
                    {isAdmin && !m.result && m.status !== 'cancelled' && (
                      <Button className="ghost compact" onClick={() => setModal('include')}>
                        <Plus size={16} /> Добавить
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
                {isAdmin && (
                  <section className="panel admin-panel" hidden={activeSection !== 'manage'}>
                    <div className="eyebrow">
                      <Shield size={13} /> АДМИНИСТРАТОР
                    </div>
                    <h2>Управление игрой</h2>
                    {!m.result &&
                      m.status !== 'cancelled' &&
                      Date.now() < new Date(m.starts_at).getTime() && (
                        <Button
                          className="ghost danger"
                          disabled={busy}
                          onClick={() => setModal('cancel')}
                        >
                          Отменить игру
                        </Button>
                      )}
                    <Button
                      disabled={busy || m.status === 'cancelled'}
                      className="secondary"
                      onClick={() => setModal('edit')}
                    >
                      Изменить параметры
                    </Button>
                    {m.status === 'draft' && (
                      <Button disabled={busy} onClick={() => void action('open')}>
                        Открыть сбор
                      </Button>
                    )}
                    {m.status === 'open' && (
                      <Button disabled={busy} onClick={() => setModal('finalize')}>
                        Финализировать сбор <Flag size={16} />
                      </Button>
                    )}
                    {m.status === 'finalized' && !auctionRunning && (
                      <Button disabled={busy} onClick={() => openLineup(m.id)}>
                        Подобрать составы
                      </Button>
                    )}
                    {m.status === 'approved' && (
                      <Button disabled={busy} onClick={() => void action('publish')}>
                        Опубликовать составы <ArrowUpRight size={16} />
                      </Button>
                    )}
                    <Button
                      disabled={busy}
                      className="ghost"
                      onClick={() =>
                        void run(async () => {
                          setHistory(await api(`/matches/${m.id}/history`))
                          setModal('history')
                        })
                      }
                    >
                      История изменений
                    </Button>
                  </section>
                )}
                {isAdmin && m.publications.length > 0 && (
                  <section className="panel" hidden={activeSection !== 'manage'}>
                    <h3>Публикации</h3>
                    {m.publications.map((p) => (
                      <div className="publication" key={p.id}>
                        <strong>
                          {p.kind === 'teams'
                            ? 'Составы'
                            : p.kind === 'cancellation'
                              ? 'Отмена игры'
                              : p.kind === 'auction_start'
                                ? 'Старт аукциона'
                                : p.kind === 'result'
                                  ? 'Итог игры'
                                  : p.kind === 'auction_lot'
                                    ? 'Аукцион'
                                    : 'Сбор'}
                        </strong>
                        <span>
                          {
                            (
                              {
                                pending: 'В очереди',
                                sending: 'Отправляется',
                                sent: 'Опубликовано',
                                demo: 'Демо: отправка имитирована',
                                failed: 'Ошибка',
                                uncertain: 'Проверьте чат',
                                cancelled: 'Отменено',
                              } as Record<string, string>
                            )[p.status]
                          }
                          {p.stale ? ' · неактуально' : ''}
                        </span>
                        {p.error && <p className="error-text">{p.error}</p>}
                        {['failed', 'uncertain'].includes(p.status) && !p.stale && (
                          <Button
                            className="secondary compact"
                            disabled={busy}
                            onClick={() => {
                              if (
                                p.status !== 'uncertain' ||
                                window.confirm(
                                  'Проверьте чат: сообщение могло быть доставлено. Повторить отправку?',
                                )
                              )
                                void run(
                                  () => api(`/publications/${p.id}/retry`, 'POST'),
                                  'Повторная отправка запрошена',
                                )
                            }}
                          >
                            Повторить
                          </Button>
                        )}
                      </div>
                    ))}
                  </section>
                )}
              </aside>
            </div>
          </SectionTabs>
        </>
      )}
    </>
  )
}
