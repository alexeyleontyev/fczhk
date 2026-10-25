import { api } from './api'
import { PlayerName } from './player-name'
import { Button, Modal } from './ui'
import type { Entry, Match, Run } from './types'

function Names({ entries }: { entries: Entry[] }) {
  return entries.map((entry, index) => (
    <span key={entry.id}>
      {index > 0 && ', '}
      <PlayerName playerId={entry.player_id} alias={entry.alias} />
    </span>
  ))
}

export function FinalizeCollection({
  match: m,
  busy,
  run,
  close,
}: {
  match: Match
  busy: boolean
  run: Run
  close: () => void
}) {
  // Both flags come from the server: in_main is the current queue and selected
  // is the selection on confirmation, including any places fixed by an admin.
  const changes = (['field', 'keeper'] as const)
    .map((position) => {
      const entries = m.registrations.filter((entry) => entry.position === position)
      return {
        position,
        label: position === 'field' ? 'Полевые' : 'Вратари',
        removed: entries.filter((entry) => (entry.in_main ?? entry.selected) && !entry.selected),
        promoted: entries.filter((entry) => !(entry.in_main ?? entry.selected) && entry.selected),
      }
    })
    .filter(({ removed, promoted }) => removed.length > 0 || promoted.length > 0)
  const replacements = changes.some(({ promoted }) => promoted.length > 0)
  const selected = m.registrations.filter((entry) => entry.selected)
  return (
    <Modal title="Утвердить составы?" close={close}>
      <p>
        Пройдут первые {m.field_limit} полевых и {m.keeper_limit} вратаря с оплатой, подтверждённой
        администратором, по времени записи. Закреплённые места сохранятся.
      </p>
      {changes.length > 0 && (
        <div className="finalize-changes">
          <p>В основном списке есть игроки без подтверждённой оплаты.</p>
          {changes.map(({ position, label, removed, promoted }) => (
            <section key={position} aria-label={`Изменения: ${label}`}>
              <h3>{label}</h3>
              {removed.length > 0 && (
                <p>
                  Не войдут в сбор: <Names entries={removed} />.
                </p>
              )}
              {promoted.length > 0 ? (
                <p>
                  Из резерва войдут: <Names entries={promoted} />.
                </p>
              ) : (
                <p>В резерве нет игроков этого амплуа с подтверждённой оплатой.</p>
              )}
            </section>
          ))}
        </div>
      )}
      <p>
        В сборе будет {selected.filter((entry) => entry.position === 'field').length} /{' '}
        {m.field_limit} полевых и {selected.filter((entry) => entry.position === 'keeper').length} /{' '}
        {m.keeper_limit} вратарей. Самостоятельная запись закроется.
      </p>
      <p>
        <strong>
          {replacements
            ? 'Заменить игроков основного списка игроками из резерва и утвердить сбор?'
            : 'Утвердить сбор?'}
        </strong>
      </p>
      <div className="inline wrap">
        <Button
          disabled={busy}
          onClick={() =>
            void run(async () => {
              await api(`/matches/${m.id}/actions/finalize`, 'POST', { version: m.version })
              close()
            }, 'Сбор утверждён. Распределите команды.')
          }
        >
          Да
        </Button>
        <Button disabled={busy} className="secondary" onClick={close}>
          Нет
        </Button>
      </div>
    </Modal>
  )
}
