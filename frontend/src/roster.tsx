import { useState } from 'react'
import { Check } from 'lucide-react'
import { api } from './api'
import { Button } from './ui'
import { date, time, initial } from './format'
import type { Match, Position, Run } from './types'

export function Roster({
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
            <details className="roster-row-details">
              <summary>Подробности записи</summary>
              <small>
                {date(r.registered_at)} · {time(r.registered_at)}
                {r.forced ? ' · добавлен админом' : ''}
              </small>
            </details>
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
