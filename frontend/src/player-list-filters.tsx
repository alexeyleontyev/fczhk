type NamedPlayer = { alias: string }
type PlayerRow = NamedPlayer & { games: number }

export const DEFAULT_MIN_GAMES = '5'

export function filterPlayerNames<T extends NamedPlayer>(rows: T[], name: string): T[] {
  const query = name.trim().toLocaleLowerCase('ru-RU').replaceAll('ё', 'е')
  return rows.filter((row) =>
    row.alias.toLocaleLowerCase('ru-RU').replaceAll('ё', 'е').includes(query),
  )
}

export function filterPlayers<T extends PlayerRow>(
  rows: T[],
  name: string,
  minimumGames: string,
): T[] {
  const parsed = Number(minimumGames)
  const threshold = Number.isFinite(parsed) ? Math.max(0, Math.floor(parsed)) : 0
  return filterPlayerNames(
    rows.filter((row) => row.games > threshold),
    name,
  )
}

export function PlayerListFilters({
  name,
  setName,
  minimumGames,
  setMinimumGames,
  scope,
}: {
  name: string
  setName: (value: string) => void
  minimumGames?: string
  setMinimumGames?: (value: string) => void
  scope: string
}) {
  return (
    <div className="player-list-filters" role="group" aria-label={scope}>
      <label>
        Имя игрока
        <input
          type="search"
          value={name}
          onChange={(event) => setName(event.target.value)}
          placeholder="Найти игрока"
        />
      </label>
      {minimumGames !== undefined && setMinimumGames && (
        <label>
          Игр больше
          <input
            type="number"
            min="0"
            step="1"
            inputMode="numeric"
            value={minimumGames}
            onChange={(event) => setMinimumGames(event.target.value)}
          />
        </label>
      )}
    </div>
  )
}
