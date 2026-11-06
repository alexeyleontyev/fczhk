import { ArrowUpRight } from 'lucide-react'
import { Button } from './ui'
import type { Match, Team } from './types'

export function TeamDots({
  alias,
  team,
  onChange,
  disabled,
}: {
  alias: string
  team: Team | null
  onChange: (team: Team | null) => void
  disabled?: boolean
}) {
  return (
    <div className="team-dots" role="group" aria-label={`Команда: ${alias}`}>
      {(['white', 'black'] as Team[]).map((color) => (
        <button
          key={color}
          type="button"
          className={`team-pick ${color}`}
          aria-label={`${alias}: ${color === 'white' ? 'белые' : 'чёрные'}`}
          aria-pressed={team === color}
          disabled={disabled}
          onClick={() => onChange(team === color ? null : color)}
        >
          <span>{team === color ? '✓' : ''}</span>
        </button>
      ))}
    </div>
  )
}

export function LineupEntry({ match, onOpen }: { match: Match; onOpen: () => void }) {
  const approved = Boolean(match.team_ratings.frozen || match.result)
  const rows =
    match.result?.participants ?? match.registrations.filter((r) => r.selected && approved)
  return (
    <section className="panel lineup-entry">
      <div>
        <h2>Составы команд</h2>
        <span className="muted caption">
          {approved ? (
            <>
              ⚪ {rows.filter((r) => r.team === 'white').length} · ⚫{' '}
              {rows.filter((r) => r.team === 'black').length} · Утверждены
            </>
          ) : (
            'Состав ещё не утверждён'
          )}
        </span>
      </div>
      <Button className="secondary compact" onClick={onOpen}>
        {approved ? 'Открыть команды' : 'Сформировать команды'} <ArrowUpRight size={16} />
      </Button>
    </section>
  )
}
