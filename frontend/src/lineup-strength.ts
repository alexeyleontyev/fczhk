import type { CSSProperties } from 'react'
import type { Person } from './lineup-types'

export function communityStrength(p: Person): number | null {
  const a = p.community_attack === undefined ? p.attack : p.community_attack
  const d = p.community_defense === undefined ? p.defense : p.community_defense
  return p.position === 'keeper' ? d : a === null || d === null ? null : a + d
}

export function strengthScale(people: Person[]) {
  const known = people
    .filter((p) => p.position === 'field')
    .map(communityStrength)
    .filter((n): n is number => n !== null)
  const min = Math.min(...known),
    max = Math.max(...known)
  return (p: Person): CSSProperties => {
    const score = communityStrength(p)
    if (score === null)
      return { '--strength-fill': '#eeefeb', '--strength-border': '#cfd4ca' } as CSSProperties
    const t = Math.max(
      0,
      Math.min(
        1,
        p.position === 'keeper' ? score / 5 : max === min ? 0.5 : (score - min) / (max - min),
      ),
    )
    const a = t < 0.5 ? [238, 170, 160] : [242, 211, 143]
    const b = t < 0.5 ? [242, 211, 143] : [157, 212, 168]
    const weight = t < 0.5 ? t * 2 : (t - 0.5) * 2
    const color = a.map((v, i) => Math.round(v + (b[i] - v) * weight))
    return {
      '--strength-fill': `rgb(${color.join(',')})`,
      '--strength-border': `rgb(${color.map((v) => v - 22).join(',')})`,
    } as CSSProperties
  }
}

export function fieldTotals(people: Person[]) {
  const fields = people.filter((p) => p.position === 'field')
  const metric = (k: 'attack' | 'defense') => {
    const known = fields.map((p) => p[k]).filter((n): n is number => n !== null)
    return {
      value: known.reduce((sum, n) => sum + n, 0),
      known: known.length,
      count: fields.length,
    }
  }
  const attack = metric('attack'),
    defense = metric('defense')
  return {
    attack,
    defense,
    total: {
      value: attack.value + defense.value,
      known: attack.known + defense.known,
      count: attack.count + defense.count,
    },
  }
}

export function totalLabel(m: { value: number; known: number; count: number }) {
  return m.known
    ? `${m.known < m.count ? '≥ ' : ''}${m.value.toLocaleString('ru-RU', { maximumFractionDigits: 2 })}`
    : '—'
}
