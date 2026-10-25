import { ArrowUpRight, Flag, Plus, Shield } from 'lucide-react'
import { api } from './api'
import { publicationKind } from './format'
import { Button } from './ui'
import type { History, Match, Run } from './types'

export function GameControls({
  match: m,
  busy,
  run,
  action,
  setModal,
  setHistory,
  openLineup,
}: {
  match: Match
  busy: boolean
  run: Run
  action: (name: string) => Promise<void>
  setModal: (value: string | null) => void
  setHistory: (value: History) => void
  openLineup: (id: number) => void
}) {
  const auctionRunning = ['active', 'paused'].includes(m.auction_status || '')
  const publicationProblems = m.publications.some(
    (p) => ['failed', 'uncertain'].includes(p.status) && !p.stale,
  )
  return (
    <section className="panel game-controls" aria-label="Управление игрой">
      <div className="section-title">
        <h2>
          <Shield size={15} /> Управление игрой
        </h2>
      </div>
      <div className="inline wrap">
        {m.status === 'draft' && (
          <Button disabled={busy} onClick={() => void action('open')}>
            Открыть сбор
          </Button>
        )}
        {m.status === 'open' && (
          <Button disabled={busy} onClick={() => setModal('finalize')}>
            Утвердить составы <Flag size={16} />
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
          disabled={busy || m.status === 'cancelled'}
          className="secondary compact"
          onClick={() => setModal('edit')}
        >
          Изменить параметры
        </Button>
        <Button
          disabled={busy}
          className="ghost compact"
          onClick={() =>
            void run(async () => {
              setHistory(await api(`/matches/${m.id}/history`))
              setModal('history')
            })
          }
        >
          История изменений
        </Button>
        <Button disabled={busy} className="ghost compact" onClick={() => setModal('create')}>
          <Plus size={16} /> Новая игра
        </Button>
        {!m.result && m.status !== 'cancelled' && Date.now() < new Date(m.starts_at).getTime() && (
          <Button
            disabled={busy}
            className="ghost danger compact"
            onClick={() => setModal('cancel')}
          >
            Отменить игру
          </Button>
        )}
      </div>
      {m.publications.length > 0 && (
        <details className="game-publications" open={publicationProblems || undefined}>
          <summary>Публикации{publicationProblems ? ' · требуется проверка' : ''}</summary>
          {m.publications.map((p) => (
            <div className="publication" key={p.id}>
              <strong>{publicationKind[p.kind] || p.kind}</strong>
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
        </details>
      )}
    </section>
  )
}
