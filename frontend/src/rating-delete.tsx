import { removeRating, ratingEntry, useRatingDrafts } from './rating-drafts'
import type { Position } from './types'

export function RatingDelete({
  actor,
  player,
  alias,
  position,
  revision,
  refresh,
}: {
  actor: number
  player: number
  alias: string
  position: Position
  revision: number
  refresh: () => Promise<void>
}) {
  const entry = ratingEntry(useRatingDrafts(actor), player, position)
  return (
    <>
      <button
        type="button"
        className="text-button rating-delete"
        disabled={Boolean(entry.saving)}
        aria-label={`Удалить мою оценку: ${alias}`}
        onClick={async () => {
          if (
            !window.confirm(
              `Удалить мою оценку игрока «${alias}» (${position === 'field' ? 'полевой: атака и защита' : 'вратарь: защита'})?\nГолос перестанет участвовать в средних, включая прежнюю оценку из таблицы. Несохранённый ввод для этого амплуа будет убран. История сохранится. Позже можно оценить заново.`,
            )
          )
            return
          await removeRating(actor, player, position, revision, refresh)
        }}
      >
        Удалить мою оценку
      </button>
    </>
  )
}
