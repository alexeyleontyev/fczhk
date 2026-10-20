import type { Position, Team } from './types'

export type Point = { x: number; y: number }
export type TacticalPlayer = {
  registration_id: number
  position: Position
  attack: number | null
  defense: number | null
}

const total = (p: TacticalPlayer) =>
  p.attack !== null && p.defense !== null ? p.attack + p.defense : null
const bias = (p: TacticalPlayer) =>
  p.attack !== null && p.defense !== null ? p.attack - p.defense : 0
const stable = (a: TacticalPlayer, b: TacticalPlayer) => a.registration_id - b.registration_id

export function tacticalLayout(
  people: TacticalPlayer[],
  assignments: Record<string, Team | null>,
): Record<string, Point> {
  const result: Record<string, Point> = {}
  for (const team of ['black', 'white'] as Team[]) {
    const rows = people.filter((p) => assignments[p.registration_id] === team)
    const field = rows
      .filter((p) => p.position === 'field')
      .sort((a, b) => {
        const first = total(a),
          second = total(b)
        // Unknown ratings cannot be ranked as zero; real zero scores remain eligible.
        if (first === null) return second === null ? stable(a, b) : 1
        if (second === null) return -1
        return first - second || stable(a, b)
      })
    const substitutes = field.slice(0, Math.max(0, field.length - 7))
    const starters = field
      .slice(substitutes.length)
      .sort((a, b) => bias(b) - bias(a) || (b.attack ?? -1) - (a.attack ?? -1) || stable(a, b))
    const forward = starters.slice(0, 1)
    const others = starters
      .slice(1)
      .sort((a, b) => bias(a) - bias(b) || (b.defense ?? -1) - (a.defense ?? -1) || stable(a, b))
    // Seven starters form 3–3–1; smaller squads keep everyone on the pitch.
    const defenders = others.slice(0, Math.ceil(others.length / 2))
    const midfielders = others.slice(defenders.length)
    const place = (p: TacticalPlayer, x: number, depth: number) => {
      result[p.registration_id] = {
        x: team === 'black' ? x : 1 - x,
        y: team === 'black' ? depth : 1 - depth,
      }
    }
    for (const [line, depth] of [
      [defenders, 0.2],
      [midfielders, 0.32],
      [forward, 0.44],
    ] as const) {
      line.forEach((p, i) =>
        place(p, line.length === 3 ? 0.2 + i * 0.3 : (i + 1) / (line.length + 1), depth),
      )
    }
    substitutes.forEach((p, i) =>
      place(p, i % 2 === 0 ? 0.86 : 0.14, 0.065 + Math.floor(i / 2) * 0.08),
    )
    rows
      .filter((p) => p.position === 'keeper')
      .sort(stable)
      .forEach((p, i, keepers) => place(p, (i + 1) / (keepers.length + 1), 0.065))
  }
  return result
}
