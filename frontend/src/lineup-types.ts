import type { BalanceRun, Position, Team } from './types'
import type { Point } from './tactical-layout'

export type Person = {
  registration_id: number
  player_id: number
  alias: string
  position: Position
  attack: number | null
  defense: number | null
  community_attack?: number | null
  community_defense?: number | null
  game_mu: number | null
}
export type Source = 'manual' | 'community' | 'game' | 'auction' | 'proposal'
export type Assignments = Record<string, Team | null>
export type Lineup = {
  version: number
  roster_version: number
  fingerprint: string
  players: Person[]
  official_players: Person[] | null
  official_assignments: Assignments | null
  assignments: Assignments
  placements: Record<string, Point>
  editable: boolean
  share_available?: boolean
  min_field_players: number
  require_two_keepers: boolean
  auction: {
    id: number
    status: string
    assignments: Record<string, Team>
    prices: Record<string, number>
  } | null
}
export type Preview = Lineup & { method: 'community' | 'game'; result: BalanceRun['result'] }
export type Draft = Pick<
  Lineup,
  'version' | 'roster_version' | 'fingerprint' | 'assignments' | 'placements'
> & {
  source: Source
  variant: number
  proposal_id?: number
  proposal_revision?: number
}
export type Proposal = {
  id: number
  author_id: number
  author: string
  revision: number
  roster_version: number
  fingerprint: string
  updated_at: string
  roster_stale: boolean
  ratings_changed: boolean
  players: Person[]
  assignments: Assignments
  placements: Record<string, Point>
}
export type Proposals = { proposals: Proposal[]; mine_revision: number; editable: boolean }
