import { test, expect } from '@playwright/test'
import { tacticalLayout, type TacticalPlayer } from '../src/tactical-layout'
import type { Team } from '../src/types'

function squad(): TacticalPlayer[] {
  return [
    { registration_id: 1, position: 'field', attack: 1, defense: 5 },
    { registration_id: 2, position: 'field', attack: 1, defense: 4 },
    { registration_id: 3, position: 'field', attack: 2, defense: 5 },
    { registration_id: 4, position: 'field', attack: 3, defense: 3 },
    { registration_id: 5, position: 'field', attack: 3.5, defense: 3.5 },
    { registration_id: 6, position: 'field', attack: 2.5, defense: 2.5 },
    { registration_id: 7, position: 'field', attack: 5, defense: 1 },
    { registration_id: 8, position: 'field', attack: 1, defense: 0 },
    { registration_id: 9, position: 'keeper', attack: null, defense: 0 },
  ]
}

function assignment(people: TacticalPlayer[], team: Team) {
  return Object.fromEntries(people.map((p) => [p.registration_id, team]))
}

for (const team of ['black', 'white'] as Team[]) {
  test(`${team}: lowest field total goes to the corner, seven starters form 3–3–1`, () => {
    const people = squad()
    const positions = tacticalLayout(people, assignment(people, team))
    const depth = (id: number) => (team === 'black' ? positions[id].y : 1 - positions[id].y)
    expect(positions[8].x).toBeCloseTo(team === 'black' ? 0.86 : 0.14)
    expect(depth(8)).toBeCloseTo(0.065)
    expect(positions[9].x).toBe(0.5)
    expect(depth(9)).toBeCloseTo(0.065)
    for (const id of [1, 2, 3]) expect(depth(id)).toBeCloseTo(0.2)
    for (const id of [4, 5, 6]) expect(depth(id)).toBeCloseTo(0.32)
    expect(depth(7)).toBeCloseTo(0.44)
    expect(Object.keys(positions)).toHaveLength(9)
  })
}

test('missing ratings are not treated as zero; real zero can be the weakest player', () => {
  const people = squad()
  people[0].attack = people[0].defense = null
  let positions = tacticalLayout(people, assignment(people, 'black'))
  expect(positions[8]).toEqual({ x: 0.86, y: 0.065 })
  expect(positions[1].y).toBeGreaterThan(0.065)
  people[0].attack = people[0].defense = 0
  positions = tacticalLayout(people, assignment(people, 'black'))
  expect(positions[1]).toEqual({ x: 0.86, y: 0.065 })
  expect(positions[8].y).toBeGreaterThan(0.065)
})

test('small squads keep all field players in play; unassigned players are absent', () => {
  const people = squad().filter((p) => p.registration_id !== 8)
  const positions = tacticalLayout(people, assignment(people, 'white'))
  for (const p of people.filter((p) => p.position === 'field')) {
    expect(positions[p.registration_id].y).toBeLessThan(0.9)
  }
  expect(tacticalLayout(people, {})).toEqual({})
})

test('equal or missing ratings give stable positions independently of response order', () => {
  for (const score of [null, 3]) {
    const people = squad().map((p) =>
      p.position === 'field' ? { ...p, attack: score, defense: score } : p,
    )
    const assignments = assignment(people, 'black')
    expect(tacticalLayout([...people].reverse(), assignments)).toEqual(
      tacticalLayout(people, assignments),
    )
  }
})

test('both teams are placed independently and extra field players remain visible at the edge', () => {
  const black = squad()
  const white = squad().map((p) => ({ ...p, registration_id: p.registration_id + 20 }))
  black.push({ registration_id: 10, position: 'field', attack: 0, defense: 0 })
  const positions = tacticalLayout([...black, ...white], {
    ...assignment(black, 'black'),
    ...assignment(white, 'white'),
  })
  expect(Object.keys(positions)).toHaveLength(19)
  expect(positions[10].y).toBeCloseTo(0.065)
  expect(positions[8].y).toBeCloseTo(0.065)
  expect(positions[28].y).toBeCloseTo(0.935)
  for (const p of black) expect(positions[p.registration_id].y).toBeLessThan(0.5)
  for (const p of white) expect(positions[p.registration_id].y).toBeGreaterThan(0.5)
})
