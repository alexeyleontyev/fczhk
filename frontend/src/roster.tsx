import { api } from './api'
import { Button } from './ui'
import { date, time, initial } from './format'
import type { Entry, Match, Position, Run } from './types'
import { PlayerName } from './player-name'
import { PaymentStatus } from './payment-status'

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
  const main = (r: Entry) => r.in_main ?? r.selected
  const registrations = [
    ...m.registrations.filter((r) => r.position === 'field'),
    ...m.registrations.filter((r) => r.position === 'keeper'),
  ]
  const mainPlayers = registrations.filter(main)
  const mainField = mainPlayers.filter((r) => r.position === 'field')
  const hasReportedPayments = registrations.some(
    (r) => r.position === 'field' && r.payment_reported && !r.paid,
  )
  const groups = [
    { title: 'Основной список', className: 'roster-main', rows: mainPlayers },
    { title: 'Резерв', className: 'roster-reserve', rows: registrations.filter((r) => !main(r)) },
  ]
  return (
    <>
      {(['field', 'keeper'] as Position[]).map((position) => {
        const regs = m.registrations.filter((r) => r.position === position)
        const next = regs.find((r) => !r.selected && (position === 'keeper' || r.paid))
        const room =
          regs.filter((r) => r.selected).length <
          (position === 'field' ? m.field_limit : m.keeper_limit)
        return (
          admin &&
          ['finalized', 'approved'].includes(m.status) &&
          room &&
          next && (
            <div className="reserve-callout" key={position}>
              <span>
                {position === 'keeper' ? 'Следующий вратарь:' : 'Следующий оплативший:'}{' '}
                <strong>
                  <PlayerName playerId={next.player_id} alias={next.alias} />
                </strong>
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
          )
        )
      })}
      {groups.map((group) => (
        <section className={group.className} key={group.title} aria-label={group.title}>
          <h3>
            {group.title} · {group.rows.length}
          </h3>
          {group.className === 'roster-main' && (
            <div className={admin ? 'inline' : undefined}>
              <p className="muted caption">
                Полевые: {mainField.length} / {m.field_limit} · Вратари:{' '}
                {mainPlayers.length - mainField.length} / {m.keeper_limit}
                <br />
                Отметили оплату: {mainField.filter((r) => r.payment_reported).length} ·
                Подтверждено: {mainField.filter((r) => r.paid).length}
              </p>
              {admin && (
                <Button
                  className="secondary compact"
                  disabled={busy || !hasReportedPayments}
                  onClick={() =>
                    void run(
                      () =>
                        api(`/matches/${m.id}/payments/confirm-all`, 'POST', {
                          version: m.version,
                        }),
                      'Отмеченные оплаты подтверждены',
                    )
                  }
                >
                  Подтвердить всех
                </Button>
              )}
            </div>
          )}
          {!group.rows.length && (
            <p className="muted empty-small">
              {group.className === 'roster-reserve' ? 'Резерв пока пуст' : 'Пока нет участников'}
            </p>
          )}
          {group.rows.map((r) => (
            <div className={`roster-row ${main(r) ? '' : 'reserve-row'}`} key={r.id}>
              <span className="number">{r.queue.toString().padStart(2, '0')}</span>
              <span className="avatar">{initial(r.alias)}</span>
              <div className="roster-name">
                <strong>
                  <PlayerName playerId={r.player_id} alias={r.alias} />{' '}
                  {r.position === 'keeper' && <span className="guest-label">вратарь</span>}
                  {r.guest && <span className="guest-label">гость</span>}
                </strong>
                <time className="roster-registration-time" dateTime={r.registered_at}>
                  {date(r.registered_at)} · {time(r.registered_at)} МСК
                </time>
              </div>
              <div className="roster-actions">
                {r.position === 'keeper' ? (
                  <span className="payment-status positive">
                    <span className="payment-status-label">Бесплатно</span>
                  </span>
                ) : (
                  <PaymentStatus
                    reported={Boolean(r.payment_reported)}
                    confirmed={r.paid}
                    alias={r.alias}
                    disabled={busy}
                    onReported={
                      admin
                        ? () =>
                            void run(() =>
                              api(`/matches/${m.id}/registrations/${r.id}/payment`, 'PUT', {
                                version: m.version,
                                paid: r.paid,
                                reported: !r.payment_reported,
                              }),
                            )
                        : undefined
                    }
                    onConfirmed={
                      admin
                        ? () =>
                            void run(() =>
                              api(`/matches/${m.id}/registrations/${r.id}/payment`, 'PUT', {
                                version: m.version,
                                paid: !r.paid,
                              }),
                            )
                        : undefined
                    }
                  />
                )}
                {admin && (
                  <button
                    disabled={busy}
                    className="text-button danger"
                    onClick={() => {
                      if (
                        window.confirm(
                          `Убрать ${r.alias} из сбора?\n\nОбе отметки оплаты будут сброшены. При повторной записи игрок займёт новое место в очереди. Если игрок в составе, потребуется новое распределение.`,
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
        </section>
      ))}
    </>
  )
}
