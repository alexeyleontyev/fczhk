import { useEffect, useState } from 'react'
import { api } from './api'
import { Button } from './ui'
import type { Match, Run } from './types'

type Options = { version: number; current_starts_at: string; next_starts_at: string }
const label = (value: string) =>
  new Date(value).toLocaleString('ru-RU', {
    day: 'numeric',
    month: 'long',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    timeZone: 'Europe/Moscow',
  }) + ' МСК'

export function CancelCollection({
  match,
  busy,
  run,
  close,
}: {
  match: Match
  busy: boolean
  run: Run
  close: () => void
}) {
  const [options, setOptions] = useState<Options | null>(null)
  const [advance, setAdvance] = useState<boolean | null>(null)
  const [error, setError] = useState('')
  const [revision, setRevision] = useState(0)
  useEffect(() => {
    let active = true
    setOptions(null)
    setAdvance(null)
    setError('')
    void api<Options>(`/matches/${match.id}/cancellation`)
      .then((value) => {
        if (active) setOptions(value)
      })
      .catch((e) => {
        if (active) setError((e as Error).message)
      })
    return () => {
      active = false
    }
  }, [match.id, match.version, revision])
  return (
    <form
      onSubmit={(event) => {
        event.preventDefault()
        if (!options || advance === null) return
        const reason = new FormData(event.currentTarget).get('reason')
        void run(
          async () => {
            await api(`/matches/${match.id}/cancel`, 'POST', {
              version: options.version,
              reason,
              advance_schedule: advance,
              expected_next_starts_at: advance ? options.next_starts_at : null,
            })
            close()
          },
          advance ? 'Игра отменена. Расписание перенесено.' : 'Сбор закрыт. Дата игры сохранена.',
        )
      }}
    >
      {error && (
        <p role="alert" className="alert error">
          {error}
        </p>
      )}
      {!options && !error && <p className="muted">Проверяем расписание…</p>}
      {options && (
        <fieldset className="cancellation-choice">
          <legend>
            Перенести следующую запланированную игру на {label(options.next_starts_at)}?
          </legend>
          <label>
            <span>
              <input
                type="radio"
                name="advance"
                aria-label="Да, перенести"
                checked={advance === true}
                onChange={() => setAdvance(true)}
                disabled={busy}
              />{' '}
              Да, перенести
            </span>
            <small>
              Текущая игра отменяется. Следующий сбор будет на {label(options.next_starts_at)}.
              История заявок и оплат сохранится; возврат или перенос оплаты согласуйте с
              участниками.
            </small>
          </label>
          <label>
            <span>
              <input
                type="radio"
                name="advance"
                aria-label="Нет, оставить дату"
                checked={advance === false}
                onChange={() => setAdvance(false)}
                disabled={busy}
              />{' '}
              Нет, оставить дату
            </span>
            <small>
              Текущий сбор закроется, игра останется на {label(options.current_starts_at)}.
              Записанные игроки и оплаты сохранятся. Если плановое время открытия ещё впереди, сбор
              откроется по расписанию; иначе администратор сможет открыть его вручную.
            </small>
          </label>
        </fieldset>
      )}
      <label>
        Причина отмены
        <input name="reason" required minLength={2} maxLength={300} disabled={busy} />
      </label>
      <div className="inline wrap">
        <Button disabled={busy || !options || advance === null} type="submit">
          {advance === false ? 'Отменить сбор' : 'Подтвердить отмену игры'}
        </Button>
        <Button
          className="ghost compact"
          disabled={busy}
          onClick={() => setRevision((value) => value + 1)}
        >
          Обновить вопрос
        </Button>
      </div>
    </form>
  )
}
