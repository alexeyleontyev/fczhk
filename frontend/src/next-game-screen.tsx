import { ArrowRight, CalendarDays, Plus, RefreshCw } from 'lucide-react'
import { Button } from './ui'
import { CollectionCountdown } from './collection-countdown'
import { date } from './format'
import { useLastCompleted } from './use-last-completed'
import type { Run } from './types'

export function NextGameScreen({
  isAdmin,
  busy,
  run,
  refresh,
  revision,
  openGame,
  openSchedule,
  createGame,
}: {
  isAdmin: boolean
  busy: boolean
  run: Run
  refresh: () => Promise<void>
  revision: number
  openGame: (id: number) => void
  openSchedule: () => void
  createGame: () => void
}) {
  const { match, loading, error } = useLastCompleted(revision)
  return (
    <>
      <div className="page-heading">
        <div>
          <div className="eyebrow">НАШ КЛУБ</div>
          <h1>Следующая игра</h1>
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
            <Button className="secondary compact" disabled={busy} onClick={createGame}>
              <Plus size={17} /> Новая игра
            </Button>
          )}
        </div>
      </div>
      <CollectionCountdown refresh={refresh} currentGame={null} showEmpty />
      {error && (
        <p className="alert error" role="alert">
          {error}
        </p>
      )}
      {loading && !match && <p className="muted">Загрузка последней игры…</p>}
      {match && (
        <section className="panel previous-game-panel">
          <div className="eyebrow">ПОСЛЕДНЯЯ ИГРА</div>
          <h2>{date(match.starts_at)}</h2>
          <div className="previous-game-score">
            <span>⚪ Белые</span>
            <strong>
              {match.result?.score.white} : {match.result?.score.black}
            </strong>
            <span>Чёрные ⚫</span>
          </div>
          <button className="text-button" onClick={() => openGame(match.id)}>
            Итог, голы и составы <ArrowRight size={16} />
          </button>
        </section>
      )}
      {!loading && !match && !error && <p className="muted caption">Завершённых игр пока нет.</p>}
      {isAdmin && (
        <section className="panel">
          <button className="next-game-schedule" disabled={busy} onClick={openSchedule}>
            <CalendarDays size={20} />
            <span>
              <strong>Управление → Расписание</strong>
              <small>Запланировать анонсы и открытие сборов</small>
            </span>
            <ArrowRight size={18} />
          </button>
        </section>
      )}
    </>
  )
}
