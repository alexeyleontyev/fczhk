import { date, time } from './format'
import type { Match, Team } from './types'

export function gameSummary(match: Pick<Match, 'starts_at' | 'location'>) {
  return `${date(match.starts_at)} · ${time(match.starts_at)} МСК\n${match.location}`
}

export function teamSummary(people: { alias: string; team: Team | null }[]) {
  return (['white', 'black'] as Team[])
    .map((team) => {
      const rows = people.filter((person) => person.team === team)
      return `${team === 'white' ? '⚪ Белые' : '⚫ Чёрные'} (${rows.length}): ${rows.map((person) => person.alias).join(', ') || '—'}`
    })
    .join('\n')
}
