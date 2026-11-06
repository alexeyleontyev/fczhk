import { useState } from 'react'
import { sessionVersion } from './api'
import {
  acceptRatingRevision,
  discardRatingDraft,
  ratingEntry,
  ratingInput,
  saveRatingDraft,
  useRatingDrafts,
} from './rating-drafts'
import type { Position } from './types'

export function RatingDraftFeedback({
  actor,
  player,
  position,
}: {
  actor: number
  player: number
  position: Position
}) {
  const entry = ratingEntry(useRatingDrafts(actor), player, position)
  return (
    <>
      {entry.error && <span role="alert">{entry.error}</span>}
      {entry.conflict !== undefined && (
        <div className="rating-conflict">
          <p>
            На сервере:{' '}
            {position === 'field' && `А ${ratingInput(entry.conflict?.attack) || '—'} · `}З{' '}
            {ratingInput(entry.conflict?.defense) || '—'}.
          </p>
          <button
            type="button"
            className="button secondary compact"
            onClick={() => acceptRatingRevision(actor, player, position)}
          >
            Использовать мой ввод
          </button>
          <button
            type="button"
            className="text-button"
            onClick={() => discardRatingDraft(actor, player, position)}
          >
            Использовать оценку сервера
          </button>
          <small>После этого нажмите «Сохранить». Изменится ваша оценка на сервере.</small>
        </div>
      )}
    </>
  )
}
export function RatingDraftBar({
  actor,
  refresh,
}: {
  actor: number
  refresh: () => Promise<void>
}) {
  const entries = useRatingDrafts(actor)
  const drafts = Object.values(entries).flatMap((e) => (e.draft ? [e.draft] : []))
  const [saving, setSaving] = useState(false),
    [message, setMessage] = useState('')
  const pending = saving || Object.values(entries).some((e) => e.saving)
  if (!drafts.length && !message) return null
  async function saveAll() {
    setSaving(true)
    let saved = 0
    const session = sessionVersion()
    for (const draft of drafts) {
      if (session !== sessionVersion()) break
      if (await saveRatingDraft(actor, draft.playerId, draft.position)) saved++
    }
    setMessage(`Сохранено оценок: ${saved} из ${drafts.length}.`)
    if (saved)
      try {
        await refresh()
      } catch {
        setMessage(
          `Сохранено оценок: ${saved}. Не удалось обновить общие баллы; обновите страницу позже.`,
        )
      }
    setSaving(false)
  }
  return (
    <section className="rating-draft-bar" aria-label="Черновики оценок">
      {drafts.length > 0 && (
        <>
          <div className="inline">
            <strong>Есть несохранённые изменения: {drafts.length}</strong>
            <button className="button compact" disabled={pending} onClick={() => void saveAll()}>
              {saving ? 'Сохраняем…' : 'Сохранить все'}
            </button>
          </div>
          <details>
            <summary>Черновики, включая скрытые фильтрами</summary>
            <p className="muted caption">
              Ввод сохранён в этом браузере. Общие оценки изменятся после отправки.
            </p>
            {drafts.map((d) => (
              <div className="rating-draft-item" key={`${d.playerId}:${d.position}`}>
                <span>
                  <b>{d.alias}</b> ·{' '}
                  {d.position === 'field' ? `А ${d.attack || '—'} · ` : 'Вратарь · '}З{' '}
                  {d.defense || '—'}
                </span>
                <button
                  className="text-button"
                  disabled={pending}
                  onClick={() => discardRatingDraft(actor, d.playerId, d.position)}
                >
                  Убрать черновик
                </button>
                <RatingDraftFeedback actor={actor} player={d.playerId} position={d.position} />
              </div>
            ))}
          </details>
        </>
      )}
      {message && (
        <p role="status">
          {message}{' '}
          <button className="text-button" onClick={() => setMessage('')}>
            Скрыть
          </button>
        </p>
      )}
    </section>
  )
}
