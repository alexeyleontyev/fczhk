import { StrictMode, useEffect, useRef, useState, type ReactNode, type FormEvent } from 'react'
import { createRoot } from 'react-dom/client'
import {
  ArrowUpRight,
  CalendarDays,
  Check,
  CircleUserRound,
  Clock3,
  Flag,
  MapPin,
  Plus,
  RefreshCw,
  Settings2,
  Shield,
  Users,
  X,
} from 'lucide-react'
import { api, hasToken, setToken } from './api'
import { AutomaticTeams, RatingAverages, RatingFlow, TeamMeans, TemporaryRatings } from './ratings'
import type { Entry, Match, Player, Position, Team, Template } from './types'
import './style.css'

const date = (s: string) =>
  new Date(s).toLocaleDateString('ru-RU', {
    day: 'numeric',
    month: 'long',
    timeZone: 'Europe/Moscow',
  })
const time = (s: string) =>
  new Date(s).toLocaleTimeString('ru-RU', {
    hour: '2-digit',
    minute: '2-digit',
    timeZone: 'Europe/Moscow',
  })
const money = (n: number) => (n / 100).toLocaleString('ru-RU') + ' ₽'
const status = {
  draft: 'Черновик',
  open: 'Запись открыта',
  finalized: 'Сбор завершен',
  approved: 'Команды готовы',
}
const initial = (name: string) =>
  name
    .split(' ')
    .map((x) => x[0])
    .slice(0, 2)
    .join('')
type Run = (work: () => Promise<unknown>, success?: string) => Promise<void>

function Button({
  children,
  onClick,
  className = '',
  disabled,
  type = 'button',
}: {
  children: ReactNode
  onClick?: () => void
  className?: string
  disabled?: boolean
  type?: 'button' | 'submit'
}) {
  return (
    <button type={type} className={`button ${className}`} onClick={onClick} disabled={disabled}>
      {children}
    </button>
  )
}

function Modal({
  title,
  children,
  close,
}: {
  title: string
  children: ReactNode
  close: () => void
}) {
  const ref = useRef<HTMLElement>(null)
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null
    const overflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    ref.current?.querySelector<HTMLElement>('input, select, button')?.focus()
    const keys = (event: KeyboardEvent) => {
      if (event.key === 'Escape') close()
      if (event.key !== 'Tab') return
      const elements = Array.from(
        ref.current?.querySelectorAll<HTMLElement>(
          'button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled)',
        ) || [],
      )
      const first = elements[0],
        last = elements[elements.length - 1]
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault()
        last?.focus()
      }
      if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault()
        first?.focus()
      }
    }
    document.addEventListener('keydown', keys)
    return () => {
      document.body.style.overflow = overflow
      document.removeEventListener('keydown', keys)
      previous?.focus()
    }
  }, [title])
  return (
    <div className="scrim" onClick={close}>
      <section
        ref={ref}
        className="modal"
        role="dialog"
        aria-modal="true"
        aria-label={title}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="section-title">
          <h2>{title}</h2>
          <button className="icon-button" aria-label="Закрыть" onClick={close}>
            <X />
          </button>
        </div>
        {children}
      </section>
    </div>
  )
}

function App() {
  const [me, setMe] = useState<Player | null>(null)
  const [matches, setMatches] = useState<Match[]>([])
  const [players, setPlayers] = useState<Player[]>([])
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [tab, setTab] = useState('game')
  const [demo, setDemo] = useState(false)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState<{ text: string; error: boolean } | null>(null)
  const [modal, setModal] = useState<string | null>(null)
  const [template, setTemplate] = useState<Template | null>(null)
  const [search, setSearch] = useState('')
  const [ratingTarget, setRatingTarget] = useState<number | null>(null)
  const [history, setHistory] = useState<{
    audit: { id: number; action: string; data: unknown; at: string }[]
    teams: { version: number; teams: { alias: string; team: Team }[]; at: string }[]
  } | null>(null)

  async function refresh() {
    const [u, games, people] = await Promise.all([
      api<Player>('/me'),
      api<Match[]>('/matches'),
      api<Player[]>('/players'),
    ])
    setMe(u)
    setMatches(games)
    setPlayers(people)
  }
  const run: Run = async (work, success) => {
    if (busy) return
    setBusy(true)
    setNotice(null)
    try {
      await work()
      await refresh()
      if (success) setNotice({ text: success, error: false })
    } catch (e) {
      setNotice({ text: (e as Error).message, error: true })
      try {
        await refresh()
      } catch {
        /* login unavailable */
      }
    } finally {
      setBusy(false)
    }
  }

  useEffect(() => {
    void (async () => {
      try {
        const health = await api<{ demo: boolean }>('/health')
        setDemo(health.demo)
        const tg = window.Telegram?.WebApp
        tg?.ready()
        tg?.expand()
        if (tg?.initData) {
          const login = await api<{ token: string }>('/auth/telegram', 'POST', {
            init_data: tg.initData,
          })
          setToken(login.token)
        }
        if (hasToken()) await refresh()
        const param = tg?.initDataUnsafe?.start_param
        if (param?.startsWith('game_')) setSelectedId(Number(param.slice(5)))
        else {
          const game = Number(new URLSearchParams(window.location.search).get('game'))
          if (Number.isInteger(game) && game > 0) setSelectedId(game)
        }
      } catch (e) {
        setNotice({ text: (e as Error).message, error: true })
      } finally {
        setLoading(false)
      }
    })()
  }, [])

  const upcoming = [...matches]
    .filter((m) => new Date(m.starts_at) > new Date())
    .sort((a, b) => a.starts_at.localeCompare(b.starts_at))[0]
  const m = matches.find((x) => x.id === selectedId) || upcoming || matches[0]
  const isAdmin = Boolean(me?.is_admin)
  const mine = m?.registrations.find((r) => r.player_id === me?.id)

  async function loginDemo(role: string) {
    await run(async () => {
      const data = await api<{ token: string }>(`/auth/demo/${role}`, 'POST')
      setToken(data.token)
      setTab('game')
    })
  }
  const action = (name: string) =>
    run(
      () => api(`/matches/${m.id}/actions/${name}`, 'POST', { version: m.version }),
      name === 'publish' ? 'Публикация поставлена в очередь' : 'Сохранено',
    )

  if (loading)
    return (
      <div className="welcome">
        <div className="brand-ball">Ф</div>
        <p>Открываем клуб…</p>
      </div>
    )
  if (!me)
    return (
      <div className="welcome">
        <div className="eyebrow">ФУТБОЛЬНОЕ СООБЩЕСТВО</div>
        <h1>
          Пятница.
          <br />
          <em>Время играть.</em>
        </h1>
        <p>
          Запись, команды и свой круг игроков.
          <br />
          Всё рядом, в Telegram.
        </p>
        {notice && (
          <div className="alert error" role="alert">
            {notice.text}
          </div>
        )}
        {demo ? (
          <div className="welcome-actions">
            <span className="tag">Локальная демонстрация</span>
            <Button onClick={() => void loginDemo('admin')} disabled={busy}>
              Войти администратором <ArrowUpRight size={18} />
            </Button>
            <Button className="secondary" onClick={() => void loginDemo('player')} disabled={busy}>
              Войти игроком
            </Button>
            <small>Демонстрационные имена и игра. Сообщения в Telegram не отправляются.</small>
          </div>
        ) : (
          <div className="alert">Откройте Mini App через меню Telegram-бота вашего сообщества.</div>
        )}
      </div>
    )

  return (
    <div className="app-shell">
      <header className="topbar">
        <a className="brand" href="/" aria-label="ФКЖК главная">
          <span className="brand-ball">Ф</span>
          <span>
            ФКЖК<span className="brand-caption">ПЯТНИЧНЫЙ ФУТБОЛ</span>
          </span>
        </a>
        <div className="user-chip">
          <span className="avatar small">{initial(me.alias)}</span>
          <div>
            {me.alias}
            <small>{isAdmin ? 'Администратор' : 'Игрок'}</small>
          </div>
        </div>
      </header>
      {demo && (
        <div className="demo-banner">
          <span>Демо · без реальных платежей и публикаций</span>
          <button
            onClick={() => {
              setToken('')
              setMe(null)
            }}
          >
            Сменить роль
          </button>
        </div>
      )}
      <nav className="navigation" aria-label="Главная навигация">
        {[
          ['game', CalendarDays, 'Игра'],
          ['archive', Clock3, 'Архив'],
          ['players', Users, 'Игроки'],
          ['profile', CircleUserRound, 'Профиль'],
        ].map(([id, Icon, label]) => {
          const I = Icon as typeof Users
          return (
            <button
              key={id as string}
              className={tab === id ? 'active' : ''}
              onClick={() => setTab(id as string)}
            >
              <I size={18} />
              <span>{label as string}</span>
            </button>
          )
        })}
        {isAdmin && (
          <button
            className={tab === 'settings' ? 'active' : ''}
            aria-label="Настройки"
            onClick={() =>
              void run(async () => {
                setTemplate(await api<Template>('/template'))
                setTab('settings')
              })
            }
          >
            <Settings2 size={18} />
            <span>Управление</span>
          </button>
        )}
      </nav>
      <main>
        {notice && !modal && (
          <div
            role={notice.error ? 'alert' : 'status'}
            className={`alert ${notice.error ? 'error' : 'success'}`}
          >
            <span>{notice.text}</span>
            <button aria-label="Скрыть сообщение" onClick={() => setNotice(null)}>
              <X size={16} />
            </button>
          </div>
        )}
        {tab === 'game' && (
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
                        {time(m.starts_at)} <small>МСК</small>
                      </span>
                    </h2>
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
                <div className="content-grid">
                  <div className="primary-column">
                    <section className="panel">
                      <div className="section-title">
                        <h2>Сбор на игру</h2>
                        <span className="muted">{m.registrations.length} записались</span>
                      </div>
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
                                <span
                                  style={{ width: `${Math.min(100, (amount / limit) * 100)}%` }}
                                />
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
                                      () =>
                                        api(`/matches/${m.id}/join`, 'POST', { position: 'field' }),
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
                    <section className="panel">
                      <div className="section-title">
                        <h2>Участники</h2>
                        {isAdmin && (
                          <Button className="ghost compact" onClick={() => setModal('include')}>
                            <Plus size={16} /> Добавить
                          </Button>
                        )}
                      </div>
                      <Roster match={m} admin={isAdmin} busy={busy} run={run} />
                      {isAdmin && <TemporaryRatings key={m.id} match={m} busy={busy} run={run} />}
                    </section>
                    {isAdmin && ['finalized', 'approved'].includes(m.status) && (
                      <AutomaticTeams key={m.id} match={m} busy={busy} run={run} />
                    )}
                    {['finalized', 'approved'].includes(m.status) && (
                      <TeamBoard match={m} admin={isAdmin} busy={busy} run={run} />
                    )}
                  </div>
                  <aside>
                    <section className="panel info-panel">
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
                    </section>
                    {isAdmin && (
                      <section className="panel admin-panel">
                        <div className="eyebrow">
                          <Shield size={13} /> АДМИНИСТРАТОР
                        </div>
                        <h2>Управление игрой</h2>
                        <Button
                          disabled={busy}
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
                        {m.status === 'finalized' && (
                          <Button disabled={busy} onClick={() => void action('approve')}>
                            Утвердить команды
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
                      <section className="panel">
                        <h3>Публикации</h3>
                        {m.publications.map((p) => (
                          <div className="publication" key={p.id}>
                            <strong>{p.kind === 'teams' ? 'Составы' : 'Сбор'}</strong>
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
              </>
            )}
          </>
        )}
        {tab === 'archive' && (
          <>
            <div className="page-heading">
              <div className="eyebrow">НАША ИСТОРИЯ</div>
              <h1>Все игры</h1>
            </div>
            <div className="archive-grid">
              {matches.map((game) => (
                <button
                  className="panel archive-card"
                  key={game.id}
                  onClick={() => {
                    setSelectedId(game.id)
                    setTab('game')
                  }}
                >
                  <span className={`status-pill ${game.status}`}>
                    <span />
                    {status[game.status]}
                  </span>
                  <h2>{date(game.starts_at)}</h2>
                  <p>
                    {time(game.starts_at)} МСК · {game.location}
                  </p>
                  <div>
                    <span>{game.registrations.filter((r) => r.selected).length} в составе</span>
                    <ArrowUpRight />
                  </div>
                </button>
              ))}
            </div>
            {!matches.length && (
              <Empty
                title="История начинается здесь"
                text="Созданные игры и их составы будут сохраняться в архиве."
              />
            )}
          </>
        )}
        {tab === 'players' && (
          <>
            <div className="page-heading">
              <div>
                <div className="eyebrow">СВОИ НА ПОЛЕ</div>
                <h1>
                  Игроки <span className="muted">{players.length}</span>
                </h1>
              </div>
              <div className="inline wrap">
                <Button
                  onClick={() => {
                    setRatingTarget(null)
                    setModal('ratings')
                  }}
                >
                  Оценить игроков
                </Button>
                {isAdmin && (
                  <Button onClick={() => setModal('guest')}>
                    <Plus size={17} /> Гость
                  </Button>
                )}
              </div>
            </div>
            <input
              className="search"
              placeholder="Найти по имени или alias"
              aria-label="Поиск игроков"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
            <div className="players-grid">
              {players
                .filter((p) => p.alias.toLowerCase().includes(search.toLowerCase()))
                .map((p) => (
                  <div key={p.id} className="panel player-card">
                    <span className="avatar">{initial(p.alias)}</span>
                    <div>
                      <h3>{p.alias}</h3>
                      <span className="muted">{p.guest ? 'Гость' : 'Игрок клуба'}</span>
                      <RatingAverages player={p} />
                      {!p.guest && (p.id !== me.id || isAdmin) && (
                        <button
                          className="button ghost compact"
                          aria-label={`Оценки: ${p.alias}`}
                          onClick={() => {
                            setRatingTarget(p.id)
                            setModal('ratings')
                          }}
                        >
                          {p.id === me.id ? 'Посмотреть оценки' : 'Оценить'}
                        </button>
                      )}
                    </div>
                    {isAdmin && p.guest && (
                      <button
                        className="icon-button"
                        aria-label={`Связать гостя ${p.alias}`}
                        onClick={() => setModal(`link:${p.id}`)}
                      >
                        <ArrowUpRight size={18} />
                      </button>
                    )}
                  </div>
                ))}
            </div>
          </>
        )}
        {tab === 'profile' && (
          <>
            <div className="page-heading">
              <div className="eyebrow">ЛИЧНЫЙ КАБИНЕТ</div>
              <h1>Мой профиль</h1>
            </div>
            <section className="panel profile-panel">
              <span className="avatar large">{initial(me.alias)}</span>
              <h2>{me.alias}</h2>
              <span className="tag">{isAdmin ? 'Администратор' : 'Игрок клуба'}</span>
              <RatingAverages player={me} />
              <form
                onSubmit={(e) => {
                  e.preventDefault()
                  const alias = new FormData(e.currentTarget).get('alias')
                  void run(() => api('/me', 'PATCH', { alias }), 'Имя обновлено')
                }}
              >
                <label>
                  Игровой alias
                  <input
                    name="alias"
                    defaultValue={me.alias}
                    required
                    minLength={2}
                    maxLength={60}
                  />
                </label>
                <Button type="submit" disabled={busy}>
                  Сохранить имя
                </Button>
              </form>
              <p className="muted caption">
                Ваше имя в заявках и составах. Профиль привязан к аккаунту Telegram.
              </p>
            </section>
          </>
        )}
        {tab === 'settings' && isAdmin && template && (
          <>
            <div className="page-heading">
              <div className="eyebrow">РЕГУЛЯРНЫЙ ФУТБОЛ</div>
              <h1>Расписание и шаблон</h1>
            </div>
            <section className="panel form-panel">
              <p>
                Автоматическое открытие — вторник, 12:00 МСК. Игра — ближайшая пятница. Изменения
                шаблона не меняют уже созданные игры.
              </p>
              <TemplateForm
                template={template}
                busy={busy}
                save={(data) =>
                  run(
                    async () => setTemplate(await api<Template>('/template', 'PUT', data)),
                    'Шаблон сохранен',
                  )
                }
              />
            </section>
          </>
        )}
      </main>
      <footer>
        <span>ФКЖК</span>
        <span>Пятница объединяет.</span>
        <span>Время — московское</span>
      </footer>
      {notice && modal && (
        <div
          role={notice.error ? 'alert' : 'status'}
          className={`alert modal-toast ${notice.error ? 'error' : 'success'}`}
        >
          <span>{notice.text}</span>
          <button aria-label="Скрыть сообщение" onClick={() => setNotice(null)}>
            <X size={16} />
          </button>
        </div>
      )}
      {modal === 'ratings' && (
        <Modal title="Оценки игроков" close={() => setModal(null)}>
          <RatingFlow me={me} players={players} target={ratingTarget} run={run} busy={busy} />
        </Modal>
      )}
      {modal === 'create' && (
        <Modal title="Новая игра" close={() => setModal(null)}>
          <GameForm
            template={template}
            busy={busy}
            save={(data) =>
              run(async () => {
                const created = await api<Match>('/matches', 'POST', data)
                setSelectedId(created.id)
                setModal(null)
              }, 'Черновик создан. Теперь можно открыть сбор.')
            }
          />
        </Modal>
      )}
      {modal === 'edit' && m && (
        <Modal title="Параметры игры" close={() => setModal(null)}>
          <GameForm
            match={m}
            busy={busy}
            save={(data) =>
              run(async () => {
                await api(`/matches/${m.id}`, 'PUT', { ...data, version: m.version })
                setModal(null)
              }, 'Параметры сохранены')
            }
          />
        </Modal>
      )}
      {modal === 'finalize' && m && (
        <Modal title="Завершить сбор?" close={() => setModal(null)}>
          <p>
            Пройдут первые {m.field_limit} оплативших полевых и {m.keeper_limit} вратаря по времени
            записи, с учетом закрепленных мест. При недоборе состав будет меньше. Самостоятельная
            запись закроется.
          </p>
          <Button
            disabled={busy}
            onClick={() =>
              void run(async () => {
                await api(`/matches/${m.id}/actions/finalize`, 'POST', { version: m.version })
                setModal(null)
              }, 'Список финализирован. Распределите команды.')
            }
          >
            Финализировать сбор
          </Button>
        </Modal>
      )}
      {modal === 'leave' && m && (
        <Modal title="Отменить запись?" close={() => setModal(null)}>
          <p>При повторной записи время будет новым, а оплату потребуется подтвердить заново.</p>
          <Button
            disabled={busy}
            onClick={() =>
              void run(async () => {
                await api(`/matches/${m.id}/join`, 'DELETE')
                setModal(null)
              }, 'Запись отменена')
            }
          >
            Подтвердить отказ
          </Button>
        </Modal>
      )}
      {modal === 'include' && m && (
        <Modal title="Добавить в состав" close={() => setModal(null)}>
          <IncludeForm
            match={m}
            players={players}
            busy={busy}
            save={(data) =>
              run(async () => {
                await api(`/matches/${m.id}/participants`, 'POST', { ...data, version: m.version })
                setModal(null)
              }, 'Участник добавлен. Распределите команды заново.')
            }
            newGuest={() => setModal('guest')}
          />
        </Modal>
      )}
      {modal === 'guest' && (
        <Modal title="Новый гость" close={() => setModal(null)}>
          <p>Сначала проверьте каталог: для одного человека используем одну карточку.</p>
          <form
            onSubmit={(e) => {
              e.preventDefault()
              const alias = new FormData(e.currentTarget).get('alias')
              void run(async () => {
                await api('/players/guests', 'POST', { alias })
                setModal(tab === 'game' ? 'include' : null)
              }, 'Карточка гостя создана')
            }}
          >
            <label>
              Имя / alias
              <input name="alias" required minLength={2} maxLength={60} />
            </label>
            <Button disabled={busy} type="submit">
              Создать карточку
            </Button>
          </form>
        </Modal>
      )}
      {modal?.startsWith('link:') && (
        <Modal title="Связать гостя с аккаунтом" close={() => setModal(null)}>
          <p>
            Убедитесь, что обе карточки принадлежат одному человеку. История гостя сохранится. При
            заявках обеих карточек на одну игру автоматическое слияние недоступно.
          </p>
          <form
            onSubmit={(e) => {
              e.preventDefault()
              const target_id = Number(new FormData(e.currentTarget).get('target'))
              void run(async () => {
                await api(`/players/${modal.split(':')[1]}/link`, 'POST', { target_id })
                setModal(null)
              }, 'Гость связан с аккаунтом')
            }}
          >
            <label>
              Зарегистрированный игрок
              <select name="target" required>
                <option value="">Выберите игрока</option>
                {players
                  .filter((p) => !p.guest)
                  .map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.alias}
                    </option>
                  ))}
              </select>
            </label>
            <Button disabled={busy} type="submit">
              Подтвердить связь
            </Button>
          </form>
        </Modal>
      )}
      {modal === 'history' && history && (
        <Modal title="История изменений" close={() => setModal(null)}>
          {history.teams.map((t) => (
            <details key={t.version}>
              <summary>
                Состав версии {t.version} · {date(t.at)}
              </summary>
              {t.teams.map((p, i) => (
                <p key={i}>
                  {p.team === 'white' ? '⚪' : '⚫'} {p.alias}
                </p>
              ))}
            </details>
          ))}
          {history.audit.map((a) => (
            <div className="history-row" key={a.id}>
              <strong>{a.action}</strong>
              <small>
                {date(a.at)} {time(a.at)}
              </small>
              <code>{JSON.stringify(a.data)}</code>
            </div>
          ))}
        </Modal>
      )}
    </div>
  )
}

function Empty({ title, text }: { title: string; text: string }) {
  return (
    <section className="panel empty">
      <CalendarDays size={36} />
      <h2>{title}</h2>
      <p>{text}</p>
    </section>
  )
}

function Roster({
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
  const [position, setPosition] = useState<Position>('field')
  const regs = m.registrations.filter((r) => r.position === position)
  const next = regs.find((r) => !r.selected && r.paid)
  const selectedCount = regs.filter((r) => r.selected).length
  const room = selectedCount < (position === 'field' ? m.field_limit : m.keeper_limit)
  return (
    <>
      <div className="segments">
        <button
          className={position === 'field' ? 'active' : ''}
          onClick={() => setPosition('field')}
        >
          Полевые <span>{m.registrations.filter((r) => r.position === 'field').length}</span>
        </button>
        <button
          className={position === 'keeper' ? 'active' : ''}
          onClick={() => setPosition('keeper')}
        >
          Вратари <span>{m.registrations.filter((r) => r.position === 'keeper').length}</span>
        </button>
      </div>
      {admin && ['finalized', 'approved'].includes(m.status) && room && next && (
        <div className="reserve-callout">
          <span>
            Следующий оплативший: <strong>{next.alias}</strong>
          </span>
          <Button
            className="secondary compact"
            disabled={busy}
            onClick={() =>
              void run(
                () => api(`/matches/${m.id}/promote`, 'POST', { version: m.version, position }),
                'Игрок переведен из резерва',
              )
            }
          >
            В состав
          </Button>
        </div>
      )}
      {regs.length === 0 && <p className="muted empty-small">Пока никто не записался</p>}
      {regs.map((r) => (
        <div className={`roster-row ${r.selected ? '' : 'reserve-row'}`} key={r.id}>
          <span className="number">{r.queue.toString().padStart(2, '0')}</span>
          <span className="avatar">{initial(r.alias)}</span>
          <div className="roster-name">
            <strong>
              {r.alias} {r.guest && <span className="guest-label">гость</span>}
            </strong>
            <small>
              {date(r.registered_at)} · {time(r.registered_at)}
              {r.forced ? ' · добавлен админом' : ''}
            </small>
            <span className={`mini-state ${r.selected ? 'green' : ''}`}>
              {
                (
                  {
                    provisional: 'Предварительно проходит',
                    selected: 'В составе',
                    reserve: 'Резерв',
                    unpaid: 'Ожидает оплаты',
                  } as Record<string, string>
                )[r.state]
              }
            </span>
          </div>
          <div className="roster-actions">
            {admin ? (
              <button
                disabled={busy}
                className={`payment-button ${r.paid ? 'paid' : ''}`}
                aria-label={`${r.paid ? 'Снять оплату' : 'Подтвердить оплату'}: ${r.alias}`}
                onClick={() =>
                  void run(() =>
                    api(`/matches/${m.id}/registrations/${r.id}/payment`, 'PUT', {
                      version: m.version,
                      paid: !r.paid,
                    }),
                  )
                }
              >
                {r.paid ? (
                  <>
                    <Check size={14} /> Оплачен
                  </>
                ) : (
                  'Отметить оплату'
                )}
              </button>
            ) : (
              <span className={`payment-label ${r.paid ? 'paid' : ''}`}>
                {r.paid ? '✓ Оплачен' : 'Не оплачен'}
              </span>
            )}
            {admin && (
              <button
                disabled={busy}
                className="text-button danger"
                onClick={() => {
                  if (
                    window.confirm(
                      `Убрать ${r.alias} из сбора? Если игрок в составе, потребуется новое распределение.`,
                    )
                  )
                    void run(
                      () =>
                        api(`/matches/${m.id}/registrations/${r.id}/remove`, 'POST', {
                          version: m.version,
                        }),
                      'Участник удален',
                    )
                }}
              >
                Убрать
              </button>
            )}
          </div>
        </div>
      ))}
    </>
  )
}

function TeamBoard({
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
  const regs = m.registrations.filter((r) => r.selected)
  const move = (r: Entry, team: Team | null) =>
    run(() =>
      api(`/matches/${m.id}/teams`, 'PUT', {
        version: m.version,
        assignments: Object.fromEntries(regs.map((x) => [x.id, x.id === r.id ? team : x.team])),
      }),
    )
  return (
    <section className="panel">
      <div className="section-title">
        <h2>Составы команд</h2>
        <span className="tag">
          {m.status === 'approved'
            ? 'Утверждены'
            : m.team_ratings.method.startsWith('auto')
              ? 'Автоподбор · черновик'
              : 'Ручное распределение'}
        </span>
      </div>
      <TeamMeans summary={m.team_ratings.summary} />
      <p className="muted caption">
        Расчетные средние только полевых, после уменьшения меньшего рейтинга.{' '}
        {m.team_ratings.frozen
          ? 'Зафиксированы при утверждении.'
          : 'Исходные оценки игроков не изменяются.'}
      </p>
      {m.team_ratings.stale && (
        <p className="alert error" role="alert">
          Рейтинги изменились. Для утверждения пересчитайте варианты или начните вручную с нуля.
        </p>
      )}
      {admin && (
        <p className="muted caption">
          Выберите команду каждому игроку. Изменения сохраняются сразу. Для утверждения численность
          полевых должна отличаться не более чем на одного.
        </p>
      )}
      <div className="team-grid">
        {(['white', 'black', null] as (Team | null)[]).map((team) => {
          const list = regs.filter((r) => r.team === team)
          if (!list.length && team === null) return null
          return (
            <div className={`team ${team || 'unassigned'}`} key={team || 'none'}>
              <h3>
                <span className="team-dot" />
                {team === 'white' ? 'Белые' : team === 'black' ? 'Черные' : 'Не распределены'}
                <span>{list.length}</span>
              </h3>
              {list.map((r) => (
                <div className="team-player" key={r.id}>
                  <span>
                    {r.position === 'keeper' ? '🧤 ' : ''}
                    {r.alias}
                  </span>
                  {admin && (
                    <select
                      aria-label={`Команда: ${r.alias}`}
                      value={r.team || ''}
                      disabled={busy}
                      onChange={(e) => void move(r, (e.target.value || null) as Team | null)}
                    >
                      <option value="">—</option>
                      <option value="white">Белые</option>
                      <option value="black">Черные</option>
                    </select>
                  )}
                </div>
              ))}
            </div>
          )
        })}
      </div>
    </section>
  )
}

function GameForm({
  match,
  template,
  busy,
  save,
}: {
  match?: Match
  template?: Template | null
  busy: boolean
  save: (data: object) => Promise<void>
}) {
  const dateValue = match ? `${match.game_day}T${time(match.starts_at)}` : ''
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault()
        const f = new FormData(e.currentTarget)
        void save({
          starts_at: `${f.get('starts_at')}:00+03:00`,
          location: f.get('location'),
          description: f.get('description'),
          payment_details: f.get('payment_details'),
          cost: Math.round(Number(f.get('cost')) * 100),
        })
      }}
    >
      <label>
        Дата и время · Москва
        <input name="starts_at" type="datetime-local" defaultValue={dateValue} required />
      </label>
      <label>
        Место игры
        <input
          name="location"
          defaultValue={match?.location || template?.location}
          required
          minLength={2}
          maxLength={200}
        />
      </label>
      <label>
        Стоимость, ₽
        <input
          name="cost"
          type="number"
          min="0"
          step="0.01"
          max="1000000"
          defaultValue={(match?.cost ?? template?.cost ?? 0) / 100}
          required
        />
      </label>
      <label>
        Куда переводить
        <textarea
          name="payment_details"
          defaultValue={match?.payment_details || template?.payment_details}
          maxLength={500}
        />
      </label>
      <label>
        Описание
        <textarea
          name="description"
          defaultValue={match?.description || template?.description}
          maxLength={1500}
        />
      </label>
      <Button type="submit" disabled={busy}>
        {match ? 'Сохранить параметры' : 'Создать черновик'}
      </Button>
    </form>
  )
}

function TemplateForm({
  template: t,
  busy,
  save,
}: {
  template: Template
  busy: boolean
  save: (data: Template) => Promise<void>
}) {
  return (
    <form
      key={t.version}
      onSubmit={(e) => {
        e.preventDefault()
        const f = new FormData(e.currentTarget)
        void save({
          version: t.version,
          enabled: f.has('enabled'),
          start_time: String(f.get('start_time')),
          location: String(f.get('location')),
          description: String(f.get('description')),
          payment_details: String(f.get('payment_details')),
          cost: Math.round(Number(f.get('cost')) * 100),
        })
      }}
    >
      <label className="checkbox">
        <input type="checkbox" name="enabled" defaultChecked={t.enabled} /> Автоматически открывать
        сбор по вторникам
      </label>
      <label>
        Время игры в пятницу · Москва
        <input name="start_time" type="time" defaultValue={t.start_time} required />
      </label>
      <label>
        Место
        <input name="location" defaultValue={t.location} maxLength={200} />
      </label>
      <label>
        Стоимость, ₽
        <input name="cost" type="number" min="0" step="0.01" defaultValue={t.cost / 100} />
      </label>
      <label>
        Куда переводить
        <textarea name="payment_details" defaultValue={t.payment_details} maxLength={500} />
      </label>
      <label>
        Описание
        <textarea name="description" defaultValue={t.description} maxLength={1500} />
      </label>
      <Button type="submit" disabled={busy}>
        Сохранить шаблон
      </Button>
    </form>
  )
}

function IncludeForm({
  match: m,
  players,
  busy,
  save,
  newGuest,
}: {
  match: Match
  players: Player[]
  busy: boolean
  save: (data: object) => Promise<void>
  newGuest: () => void
}) {
  const [position, setPosition] = useState<Position>('field')
  return (
    <form
      onSubmit={(e: FormEvent<HTMLFormElement>) => {
        e.preventDefault()
        const f = new FormData(e.currentTarget)
        void save({
          player_id: Number(f.get('player')),
          position,
          replace_id: f.get('replace') ? Number(f.get('replace')) : null,
        })
      }}
    >
      <p className="muted">
        Прямое включение администратором. При заполненном составе выберите, кого заменить.
      </p>
      <label>
        Игрок
        <select name="player" required>
          <option value="">Выберите из каталога</option>
          {players
            .filter(
              (p) => !m.registrations.some((r) => r.player_id === p.id && (r.selected || r.forced)),
            )
            .map((p) => (
              <option key={p.id} value={p.id}>
                {p.alias}
                {p.guest ? ' · гость' : ''}
              </option>
            ))}
        </select>
      </label>
      <Button className="ghost compact" onClick={newGuest}>
        <Plus size={15} /> Создать нового гостя
      </Button>
      <label>
        Амплуа
        <select value={position} onChange={(e) => setPosition(e.target.value as Position)}>
          <option value="field">Полевой</option>
          <option value="keeper">Вратарь</option>
        </select>
      </label>
      <label>
        Кого заменить
        <select name="replace" key={position}>
          <option value="">Без замены — если есть место</option>
          {m.registrations
            .filter((r) => r.selected && r.position === position)
            .map((r) => (
              <option key={r.id} value={r.id}>
                {r.alias}
              </option>
            ))}
        </select>
      </label>
      <Button disabled={busy} type="submit">
        Добавить в состав
      </Button>
    </form>
  )
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
