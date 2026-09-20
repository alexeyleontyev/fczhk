export type Position = 'field' | 'keeper'
export type Team = 'white' | 'black'
export type Average = { attack: number | null; defense: number | null; count?: number }
export type Player = {
  id: number
  alias: string
  guest: boolean
  is_admin?: boolean
  ratings?: { field: Average; keeper: Average }
}
export type Entry = {
  id: number
  player_id: number
  alias: string
  guest: boolean
  position: Position
  registered_at: string
  paid: boolean
  forced: boolean
  selected: boolean
  team: Team | null
  queue: number
  state: string
  rating: Average & { source: 'community' | 'temporary' | 'missing' }
}
export type Publication = {
  id: number
  kind: string
  status: string
  stale: boolean
  stale_marked: boolean
  error: string | null
}
export type Match = {
  id: number
  starts_at: string
  game_day: string
  location: string
  description: string
  cost: number
  payment_details: string
  field_limit: number
  keeper_limit: number
  status: 'draft' | 'open' | 'finalized' | 'approved' | 'completed'
  version: number
  result: import('./results').Result | null
  auction_status: string | null
  roster_version: number
  registrations: Entry[]
  publications: Publication[]
  team_ratings: {
    summary: BalanceSummary | null
    method: string
    frozen: boolean
    stale: boolean
    run_id?: number | null
    variant?: number | null
  }
}
export type BalanceSummary = {
  white: Average & { count: number }
  black: Average & { count: number }
  attack_gap: number | null
  defense_gap: number | null
  cost: number | null
  unassigned: number
}
export type BalanceRun = {
  id: number
  stale: boolean
  roster_version: number
  created_at: string
  settings: {
    epsilon: string
    max_epsilon: string
    epsilon_step: string
    min_distance: number | null
  }
  inputs: {
    registration_id: number
    alias: string
    attack: number
    defense: number
    source: string
  }[]
  result: {
    partition_count: number
    pool_count: number
    minimum_cost: number
    epsilon_used: number
    min_distance: number
    distances: number[][]
    warnings: string[]
    variants: { assignments: Record<string, Team>; summary: BalanceSummary }[]
  }
}
export type Run = (work: () => Promise<unknown>, success?: string) => Promise<void>
export type Template = {
  version: number
  enabled: boolean
  start_time: string
  location: string
  description: string
  cost: number
  payment_details: string
}

declare global {
  interface Window {
    Telegram?: {
      WebApp: {
        initData: string
        initDataUnsafe?: { start_param?: string }
        ready: () => void
        expand: () => void
      }
    }
  }
}
