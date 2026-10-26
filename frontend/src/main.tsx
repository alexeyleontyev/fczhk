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
import { api, setToken, uploadImage } from './api'
import { RatingFlow } from './ratings'
import { PlayerStats } from './results'
import { PredictionStandings } from './predictions'
import { BrowserLogin } from './browser-login'
import { Button, Modal } from './ui'
import { initial } from './format'
import { GameForm, IncludeForm, TemplateForm } from './forms'
import { useClubData } from './use-club-data'
import { useNavigation } from './use-navigation'
import { SectionTabs } from './section-tabs'
import { TacticsScreen } from './tactics-screen'
import { GameScreen } from './game-screen'
import { NextGameScreen } from './next-game-screen'
import { FinalizeCollection } from './finalize-collection'
import { CancelCollection } from './cancel-collection'
import { isArchivedMatch } from './archived-game-screen'
import { MatchHistory } from './match-history'
import { AuctionScreen } from './auctions'
import { ArchiveScreen } from './archive-screen'
import { PlayersScreen } from './players-screen'
import { ProfileScreen } from './profile-screen'
import { PlayerName, PlayerProfilesProvider } from './player-name'
import { OperationsPanel, ScheduleExceptions, ProfileClaims } from './operations'
import { AdministratorsPanel } from './administrators'
import { defaultSeason } from './seasons'
import type { Match, Template, History, Run } from './types'
import './style.css'

function App() {
  const {
    me,
    players,
    seasons,
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
    openAuction,
    openLineup,
    back,
    canBack,
    nativeBack,
    visited,
  } = useNavigation(selectedId, setSelectedId, Boolean(me))
  const [selectedSeason, setSeason] = useState<string | null>(null)
  const season = selectedSeason ?? defaultSeason(seasons)
  const seasonFilter = { season, seasons, onSeason: setSeason }
  useEffect(() => {
    if (!me) setSeason(null)
  }, [me?.id])
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState<{ text: string; error: boolean } | null>(null)
  const [managementTab, setManagementTab] = useState('schedule')
  useEffect(() => setManagementTab('schedule'), [me?.id])
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
  const archived = isArchivedMatch(m)
  const gameHome = selectedId === null && (!m || archived)
  const activeNavigation =
    archived && !gameHome && ['game', 'lineup', 'prediction'].includes(tab)
      ? 'archive'
      : ['auction', 'lineup', 'prediction'].includes(tab)
        ? 'game'
        : tab

  async function loginDemo(role: string) {
    await run(async () => {
      const data = await api<{ token: string }>(`/auth/demo/${role}`, 'POST')
      setToken(data.token)
      await refresh(true)
    })
  }
  async function loginBrowser(token: string) {
    setToken(token)
    setNotice(null)
    // Only a 401 invalidates the session (handled centrally in api.ts).
    // A failed or navigation-aborted data request must preserve a valid login.
    await refresh(true)
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

  const content = (
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
            <PlayerName playerId={me.id} alias={me.alias} />
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
      <nav className="navigation" aria-label="Главная навигация" hidden={tab === 'auction'}>
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
              className={activeNavigation === id ? 'active' : ''}
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
        {m &&
          !gameHome &&
          ['game', 'lineup', 'prediction'].includes(tab) &&
          (!archived || tab === 'lineup') && (
            <div className="match-tabs" role="tablist" aria-label="Экраны игры">
              <button
                role="tab"
                aria-selected={['game', 'prediction'].includes(tab)}
                onClick={() => openGame(m.id)}
              >
                {archived ? 'Итог' : 'Игра'}
              </button>
              <button role="tab" aria-selected={tab === 'lineup'} onClick={() => openLineup(m.id)}>
                {archived ? 'Поле' : 'Составы'}
              </button>
            </div>
          )}
        {tab === 'lineup' && m && (
          <TacticsScreen
            key={`${m.id}:${me.id}`}
            match={m}
            me={me}
            busy={busy}
            run={run}
            onChanged={() => refresh(true)}
            onAuction={() => openAuction(m.id)}
          />
        )}
        {['game', 'prediction'].includes(tab) && gameHome && (
          <NextGameScreen
            isAdmin={isAdmin}
            busy={busy}
            run={run}
            refresh={() => refresh(true)}
            revision={dataRevision}
            openGame={openGame}
            createGame={() => setModal('create')}
            prepareGame={(data) =>
              void run(async () => {
                const planned = await api<Match>('/schedule/next/prepare', 'POST', data)
                openGame(planned.id)
                setModal('include')
              })
            }
            saveScheduledImage={async (data, file) => {
              let saved = false
              await run(async () => {
                const planned = await api<Match>('/schedule/next/prepare', 'POST', data)
                await uploadImage(
                  `/matches/${planned.id}/collection-image?version=${planned.version}`,
                  file,
                )
                saved = true
                openGame(planned.id)
              }, 'Картинка сохранена для поста открытия сбора')
              return saved
            }}
            openSchedule={() =>
              void run(async () => {
                setTemplate(await api<Template>('/template'))
                setManagementTab('schedule')
                setTab('settings')
              })
            }
          />
        )}
        {['game', 'prediction'].includes(tab) && !gameHome && (
          <GameScreen
            focusPrediction={tab === 'prediction'}
            saveImage={async (file) => {
              let saved = false
              await run(async () => {
                await uploadImage(`/matches/${m!.id}/collection-image?version=${m!.version}`, file)
                saved = true
              }, 'Картинка сохранена для поста открытия сбора')
              return saved
            }}
            removeImage={() =>
              m &&
              void run(
                () => api(`/matches/${m.id}/collection-image`, 'DELETE', { version: m.version }),
                'Картинка убрана из будущего поста',
              )
            }
            key={m?.id ?? 'empty'}
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
            openAuction={openAuction}
            openLineup={openLineup}
            revision={dataRevision}
          />
        )}
        {tab === 'auction' && m && (
          <AuctionScreen
            key={m.id}
            match={m}
            admin={isAdmin}
            busy={busy}
            run={run}
            onStatusChange={() => void run(() => refresh(true))}
            onTeams={() => openLineup(m.id)}
          />
        )}
        {tab === 'predictions' && (
          <PredictionStandings me={me.id} onPlayer={openStats} {...seasonFilter} />
        )}
        {visited('archive') && (
          <div hidden={tab !== 'archive'}>
            <ArchiveScreen
              key={season}
              onMatch={openGame}
              revision={dataRevision}
              {...seasonFilter}
            />
          </div>
        )}
        {visited('players') && (
          <div hidden={tab !== 'players'}>
            <PlayersScreen
              players={players}
              me={me}
              dataRevision={dataRevision}
              refresh={() => refresh(true)}
              {...seasonFilter}
              openStats={openStats}
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
            {...seasonFilter}
            players={players}
          />
        )}
        {tab === 'settings' && isAdmin && template && (
          <>
            <div className="page-heading">
              <h1>
                {managementTab === 'schedule'
                  ? 'Расписание и шаблон'
                  : managementTab === 'claims'
                    ? 'Привязка профилей'
                    : managementTab === 'roles'
                      ? 'Администраторы'
                      : 'Диагностика'}
              </h1>
            </div>
            <SectionTabs
              label="Разделы управления"
              value={managementTab}
              onChange={setManagementTab}
              options={[
                { value: 'schedule', label: 'Расписание' },
                { value: 'claims', label: 'Профили' },
                ...(me.is_owner ? [{ value: 'roles', label: 'Администраторы' }] : []),
                { value: 'operations', label: 'Диагностика' },
              ]}
            >
              {managementTab === 'schedule' && (
                <>
                  <section className="panel form-panel">
                    <details className="compact-explanation">
                      <summary>Как работает расписание</summary>
                      <p>
                        Открытие сбора и начало игры задаются отдельно, по московскому времени.
                        Изменения шаблона не меняют созданные игры.
                      </p>
                    </details>
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
                  <details className="panel compact-explanation">
                    <summary>Пропуски недель</summary>
                    <ScheduleExceptions />
                  </details>
                </>
              )}
              {managementTab === 'roles' && me.is_owner && (
                <AdministratorsPanel onChanged={() => refresh(true)} />
              )}
              {managementTab === 'claims' && <ProfileClaims onResolved={() => refresh(true)} />}
              {managementTab === 'operations' && <OperationsPanel onMatch={openGame} />}
            </SectionTabs>
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
        <Modal title="Профиль игрока" close={() => setModal(null)}>
          <PlayerStats
            playerId={statsTarget}
            player={players.find((p) => p.id === statsTarget)}
            viewerId={me.id}
            viewerAdmin={isAdmin}
            onRate={openRatings}
            onMatch={openGame}
            onPlayer={openStats}
            {...seasonFilter}
          />
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
          <CancelCollection match={m} busy={busy} run={run} close={() => setModal(null)} />
        </Modal>
      )}
      {modal === 'finalize' && m && (
        <FinalizeCollection match={m} busy={busy} run={run} close={() => setModal(null)} />
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
        <Modal
          title={
            m.status === 'draft' && (m.scheduled_opening_at || m.collection_paused)
              ? 'Предварительная запись'
              : 'Добавить в состав'
          }
          close={() => setModal(null)}
        >
          <IncludeForm
            match={m}
            players={players}
            busy={busy}
            save={(data) =>
              run(
                async () => {
                  await api(`/matches/${m.id}/participants`, 'POST', {
                    ...data,
                    version: m.version,
                  })
                  setModal(null)
                },
                m.status === 'draft' && (m.scheduled_opening_at || m.collection_paused)
                  ? 'Игрок добавлен в предварительную запись'
                  : 'Участник добавлен. Распределите команды заново.',
              )
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
            <strong>
              <PlayerName
                playerId={Number(modal.split(':')[1])}
                alias={players.find((p) => p.id === Number(modal.split(':')[1]))?.alias ?? 'Гость'}
              />
            </strong>
            . Убедитесь, что обе карточки принадлежат одному человеку. Аккаунт получит alias
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
          <MatchHistory history={history} />
        </Modal>
      )}
    </div>
  )
  return (
    <PlayerProfilesProvider players={players} onPlayer={openStats}>
      {content}
    </PlayerProfilesProvider>
  )
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
