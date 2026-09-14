export type Position = 'field' | 'keeper'
export type Team = 'white' | 'black'
export type Player = { id: number; alias: string; guest: boolean; is_admin?: boolean }
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
  status: 'draft' | 'open' | 'finalized' | 'approved'
  version: number
  roster_version: number
  registrations: Entry[]
  publications: Publication[]
}
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
