export type SeasonFilter = {
  season: string
  seasons: string[]
  onSeason: (season: string) => void
}

export function seasonQuery(season: string) {
  return season ? `?season=${encodeURIComponent(season)}` : ''
}

export function SeasonSelect({ season, seasons, onSeason }: SeasonFilter) {
  return (
    <label className="season-filter">
      Период статистики
      <select
        aria-label="Период статистики"
        value={season}
        onChange={(e) => onSeason(e.target.value)}
      >
        <option value="">Общая · все сезоны</option>
        {seasons.map((value) => (
          <option key={value} value={value}>
            Сезон {value}
          </option>
        ))}
      </select>
    </label>
  )
}
