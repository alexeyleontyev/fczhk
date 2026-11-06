import { RatingMark, ratingNumber } from './rating-mark'

export type ReviewScores = {
  attack: number | null
  defense: number
  attack_weight?: number | null
  defense_weight?: number | null
}

function ReviewScore({
  kind,
  value,
  weight = 1,
}: {
  kind: 'attack' | 'defense'
  value: number
  weight?: number | null
}) {
  const retained = weight ?? 1
  const status = retained === 0 ? 'excluded' : retained < 1 ? 'partial' : 'included'
  const label =
    retained === 0
      ? 'Не учтена'
      : retained < 1
        ? `Частично: ${(retained * 100).toLocaleString('ru-RU', { maximumFractionDigits: 1 })}%`
        : 'Учтена'
  return (
    <span
      className={`review-score ${status}`}
      aria-label={`${kind === 'attack' ? 'Атака' : 'Защита'} ${ratingNumber(value)}: ${label.toLocaleLowerCase('ru')}`}
    >
      <span className="review-score-value">
        <RatingMark kind={kind} /> {ratingNumber(value)}
      </span>
      <small>{label}</small>
    </span>
  )
}

export function ReviewRatings({
  review,
  keeper = false,
}: {
  review: ReviewScores
  keeper?: boolean
}) {
  return (
    <span className={`review-rating-pair ${keeper ? 'keeper' : ''}`}>
      {!keeper && review.attack !== null && (
        <ReviewScore kind="attack" value={review.attack} weight={review.attack_weight} />
      )}
      <ReviewScore kind="defense" value={review.defense} weight={review.defense_weight} />
    </span>
  )
}
