import { StrictMode, useEffect, useState } from 'react'
import { createRoot } from 'react-dom/client'
import {
  ArrowUpRight,
  ArrowLeft,
  CalendarDays,
  CircleUserRound,
  Clock3,
  Settings2,
  Users,
  Trophy,
  X,
} from 'lucide-react'
import { api, setToken } from './api'
import { RatingFlow } from './ratings'
import { PlayerStats } from './results'
import { PredictionStandings } from './predictions'
import { BrowserLogin } from './browser-login'
import { Button, Modal } from './ui'
import { date, time, initial } from './format'
import { GameForm, IncludeForm, TemplateForm } from './forms'
import { useClubData } from './use-club-data'
import { useNavigation } from './use-navigation'
import { GameScreen } from './game-screen'
import { ArchiveScreen } from './archive-screen'
import { PlayersScreen } from './players-screen'
import { ProfileScreen } from './profile-screen'
import { OperationsPanel, ScheduleExceptions, ProfileClaims } from './operations'
import { AdministratorsPanel } from './administrators'
import type { Match, Template, History, Run } from './types'
import './style.css'

function App() {
  const {
    me,
    players,
    match: m,
    setSelectedId,
    selectedId,
    dataRevision,
    demo,
    loading,
    loadError,
    refresh,
    logout,
  } = useClubData()
  const {
    tab,
    setTab,
    modal,
    setModal,
    statsTarget,
    openStats,
    ratingTarget,
    openRatings,
    openGame,
    back,
    canBack,
    nativeBack,
    visited,
  } = useNavigation(selectedId, setSelectedId, Boolean(me))
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState<{ text: string; error: boolean } | null>(null)
  const [template, setTemplate] = useState<Template | null>(null)
  const [history, setHistory] = useState<History | null>(null)
  useEffect(() => {
    if (loadError) setNotice({ text: loadError, error: true })
  }, [loadError])

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
        await refresh(true)
      } catch {
        /* login unavailable */
      }
    } finally {
      setBusy(false)
    }
  }

  const isAdmin = Boolean(me?.is_admin)

  async function loginDemo(role: string) {
    await run(async () => {
      const data = await api<{ token: string }>(`/auth/demo/${role}`, 'POST')
      setToken(data.token)
      setTab('game')
      await refresh(true)
    })
  }
  async function loginBrowser(token: string) {
    setToken(token)
    setNotice(null)
    setTab('game')
    try {
      await refresh(true)
    } catch (error) {
      setToken('')
      throw error
    }
  }
  const action = (name: string) =>
    m
      ? run(
          () => api(`/matches/${m.id}/actions/${name}`, 'POST', { version: m.version }),
          name === 'publish' ? 'Публикация поставлена в очередь' : 'Сохранено',
        )
      : Promise.resolve()

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
        ) : window.Telegram?.WebApp?.initData ? (
          <div className="alert">Откройте Mini App через меню Telegram-бота вашего сообщества.</div>
        ) : (
          <BrowserLogin onLogin={loginBrowser} />
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
            <small>{me.is_owner ? 'Владелец' : isAdmin ? 'Администратор' : 'Игрок'}</small>
          </div>
        </div>
      </header>
      {demo && (
        <div className="demo-banner">
          <span>Демо · без реальных платежей и публикаций</span>
          <button
            disabled={busy}
            onClick={() => {
              void run(logout)
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
          ['predictions', Trophy, 'Прогнозы'],
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
            disabled={busy}
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
      {canBack && !nativeBack && !modal && (
        <Button className="ghost compact back-navigation" onClick={back}>
          <ArrowLeft size={18} /> Назад
        </Button>
      )}
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
          <GameScreen
            m={m}
            isAdmin={isAdmin}
            busy={busy}
            run={run}
            refresh={() => refresh(true)}
            setModal={setModal}
            action={action}
            players={players}
            setTab={setTab}
            setHistory={setHistory}
            me={me}
          />
        )}
        {tab === 'predictions' && <PredictionStandings me={me.id} onPlayer={openStats} />}
        {visited('archive') && (
          <div hidden={tab !== 'archive'}>
            <ArchiveScreen onMatch={openGame} revision={dataRevision} />
          </div>
        )}
        {visited('players') && (
          <div hidden={tab !== 'players'}>
            <PlayersScreen
              players={players}
              me={me}
              dataRevision={dataRevision}
              openStats={openStats}
              openRatings={openRatings}
              setModal={setModal}
            />
          </div>
        )}
        {tab === 'profile' && (
          <ProfileScreen
            me={me}
            busy={busy}
            run={run}
            openGame={openGame}
            openStats={openStats}
            logout={logout}
            players={players}
          />
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
            <ScheduleExceptions />
            {me.is_owner && <AdministratorsPanel onChanged={() => refresh(true)} />}
            <ProfileClaims onResolved={() => refresh(true)} />
            <OperationsPanel onMatch={openGame} />
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
      {modal === 'stats' && statsTarget && (
        <Modal title="Статистика игрока" close={() => setModal(null)}>
          <PlayerStats playerId={statsTarget} onMatch={openGame} onPlayer={openStats} />
        </Modal>
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
                setModal(null)
                setSelectedId(created.id)
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
      {modal === 'cancel' && m && (
        <Modal title="Отменить игру?" close={() => setModal(null)}>
          <p>
            Запись и прогнозы закроются. История и оплаты сохранятся; возврат или перенос оплаты
            согласуйте с участниками.
          </p>
          <form
            onSubmit={(e) => {
              e.preventDefault()
              const reason = new FormData(e.currentTarget).get('reason')
              void run(async () => {
                await api(`/matches/${m.id}/cancel`, 'POST', { version: m.version, reason })
                setModal(null)
              }, 'Игра отменена')
            }}
          >
            <label>
              Причина отмены
              <input name="reason" required minLength={2} maxLength={300} />
            </label>
            <Button disabled={busy} type="submit">
              Подтвердить отмену игры
            </Button>
          </form>
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
                setModal(null)
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
            Карточка:{' '}
            <strong>{players.find((p) => p.id === Number(modal?.split(':')[1]))?.alias}</strong>.
            Убедитесь, что обе карточки принадлежат одному человеку. Аккаунт получит alias
            исторической карточки, история гостя сохранится. При заявках обеих карточек на одну игру
            автоматическое слияние недоступно.
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

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
