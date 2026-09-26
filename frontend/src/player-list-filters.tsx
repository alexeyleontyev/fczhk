type PlayerRow = { alias: string; games: number }

export const DEFAULT_MIN_GAMES = '5'

export function filterPlayers<T extends PlayerRow>(
  rows: T[],
  name: string,
  minimumGames: string,
): T[] {
  const query = name.trim().toLocaleLowerCase('ru-RU').replaceAll('ё', 'е')
  const parsed = Number(minimumGames)
  const threshold = Number.isFinite(parsed) ? Math.max(0, Math.floor(parsed)) : 0
  return rows.filter(
    (row) =>
      row.games > threshold &&
      row.alias.toLocaleLowerCase('ru-RU').replaceAll('ё', 'е').includes(query),
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
  minimumGames: string
  setMinimumGames: (value: string) => void
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
    </div>
  )
}
