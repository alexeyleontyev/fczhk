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
  placements: Record<string, Point> = {},
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
  // Saved positions stay in place. A player moved between teams gets an automatic
  // position, which must not end up underneath one of those saved cards.
  const pinned = new Set<number>()
  for (const p of people) {
    const point = placements[p.registration_id]
    if (
      result[p.registration_id] &&
      point &&
      point.y >= 0.5 === (assignments[p.registration_id] === 'white')
    ) {
      result[p.registration_id] = point
      pinned.add(p.registration_id)
    }
  }
  if (!pinned.size) return result
  const occupied = [...pinned].map((id) => result[id])
  const overlaps = (a: Point, b: Point) => Math.abs(a.x - b.x) < 0.27 && Math.abs(a.y - b.y) < 0.095
  for (const p of [...people].sort(stable)) {
    const preferred = result[p.registration_id]
    if (!preferred || pinned.has(p.registration_id)) continue
    if (occupied.some((point) => overlaps(preferred, point))) {
      const candidates = [preferred]
      for (let i = 0; i <= 20; i++) {
        const depth = 0.06 + i * 0.02
        for (const x of [preferred.x, 0.14, 0.2, 0.5, 0.8, 0.86]) {
          candidates.push({ x, y: assignments[p.registration_id] === 'black' ? depth : 1 - depth })
        }
      }
      candidates.sort(
        (a, b) =>
          (a.x - preferred.x) ** 2 +
          (a.y - preferred.y) ** 2 -
          ((b.x - preferred.x) ** 2 + (b.y - preferred.y) ** 2),
      )
      result[p.registration_id] =
        candidates.find((point) => occupied.every((other) => !overlaps(point, other))) ?? preferred
    }
    occupied.push(result[p.registration_id])
  }
  return result
}
