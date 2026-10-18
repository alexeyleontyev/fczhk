export type Position = 'field' | 'keeper'
export type Team = 'white' | 'black'
export type Average = { attack: number | null; defense: number | null; count?: number }
export type Player = {
  id: number
  alias: string
  guest: boolean
  is_admin?: boolean
  is_owner?: boolean
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
  cancellation_reason?: string | null
  id: number
  starts_at: string
  game_day: string
  historical: boolean
  location: string
  description: string
  cost: number
  payment_details: string
  field_limit: number
  keeper_limit: number
  status: 'draft' | 'open' | 'finalized' | 'approved' | 'completed' | 'cancelled'
  version: number
  result: import('./results').Result | null
  auction_status: string | null
  roster_version: number
  registrations: Entry[]
  publications: Publication[]
  team_ratings: {
    summary: BalanceSummary | null
    game_summary?: {
      white_mu: number
      black_mu: number
      white_total: number
      black_total: number
      mu_gap: number
    } | null
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
    method?: 'community' | 'game'
    epsilon: string
    max_epsilon: string
    epsilon_step: string
    min_distance: number | null
  }
  inputs: {
    registration_id: number
    alias: string
    attack: number | null
    defense: number | null
    source: string
    community?: Average | null
    temporary?: Average | null
    game_mu?: number
    game_sigma?: number
    game_count?: number
  }[]
  result: {
    partition_count: number
    pool_count: number
    minimum_cost: number
    epsilon_used: number
    min_distance: number
    distances: number[][]
    warnings: string[]
    variants: {
      assignments: Record<string, Team>
      summary: BalanceSummary
      game_rating?: {
        white_mu: number
        black_mu: number
        white_total: number
        black_total: number
        mu_gap: number
      }
    }[]
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

export type TelegramLoginOptions = {
  client_id: number
  nonce: string
  scope: ['profile']
  lang: 'ru'
}
export type TelegramLoginResult = { id_token?: string; error?: string }

declare global {
  interface Window {
    Telegram?: {
      WebApp?: {
        initData: string
        initDataUnsafe?: { start_param?: string }
        ready: () => void
        expand: () => void
      }
      Login?: {
        auth: (
          options: TelegramLoginOptions,
          callback: (result: TelegramLoginResult) => void,
        ) => void
        close: () => void
      }
    }
  }
}

export type History = {
  audit: { id: number; action: string; data: unknown; at: string }[]
  teams: { version: number; teams: { alias: string; team: Team }[]; at: string }[]
}
export type MatchSummary = Pick<
  Match,
  'id' | 'starts_at' | 'game_day' | 'historical' | 'location' | 'status' | 'version'
> & {
  participant_count: number
  result: { completed: boolean; score: Record<Team, number> } | null
}
