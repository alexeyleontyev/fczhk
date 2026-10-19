export const ratingNumber = (value: number | null) =>
  value === null ? '—' : value.toLocaleString('ru-RU', { maximumFractionDigits: 2 })

export function RatingMark({ kind }: { kind: 'attack' | 'defense' }) {
  return (
    <abbr className="rating-mark" title={kind === 'attack' ? 'Атака' : 'Защита'}>
      {kind === 'attack' ? 'А' : 'З'}
    </abbr>
  )
}

export function RatingPair({
  attack,
  defense,
  keeper = false,
}: {
  attack: number | null
  defense: number | null
  keeper?: boolean
}) {
  return (
    <span className="rating-pair">
      {!keeper && (
        <>
          <RatingMark kind="attack" /> {ratingNumber(attack)} ·{' '}
        </>
      )}
      <RatingMark kind="defense" /> {ratingNumber(defense)}
    </span>
  )
}
