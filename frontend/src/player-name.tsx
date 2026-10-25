import { createContext, useContext, type ReactNode } from 'react'
import type { Player } from './types'

const PlayerProfiles = createContext<{
  players: Player[]
  onPlayer: (id: number) => void
} | null>(null)

export function PlayerProfilesProvider({
  players,
  onPlayer,
  children,
}: {
  players: Player[]
  onPlayer: (id: number) => void
  children: ReactNode
}) {
  return <PlayerProfiles.Provider value={{ players, onPlayer }}>{children}</PlayerProfiles.Provider>
}

export function PlayerName({
  playerId,
  alias,
  className = '',
}: {
  playerId?: number | null
  alias: string
  className?: string
}) {
  const profiles = useContext(PlayerProfiles)
  // Older history snapshots contain names only. Link them only when unambiguous.
  const candidates = profiles?.players.filter((p) => p.alias === alias) ?? []
  const player =
    profiles?.players.find((p) => p.id === playerId) ??
    (candidates.length === 1 ? candidates[0] : undefined)
  const id = player?.id ?? playerId
  if (!profiles || id == null || player?.shared_keeper)
    return <span className={className}>{alias}</span>
  return (
    <button
      type="button"
      className={`player-name ${className}`.trim()}
      onClick={(event) => {
        event.preventDefault()
        event.stopPropagation()
        profiles.onPlayer(id)
      }}
    >
      {alias}
    </button>
  )
}
