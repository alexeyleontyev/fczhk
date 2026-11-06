import { Fragment, useState } from 'react'
import { ArrowUpRight, Check } from 'lucide-react'
import {
  changeRatingDraft,
  ratingEntry,
  ratingInput,
  saveRatingDraft,
  useRatingDrafts,
} from './rating-drafts'
import { RatingDraftFeedback } from './rating-draft-controls'
import { PlayerName } from './player-name'
import { RatingMark, ratingNumber } from './rating-mark'
import { CommunityRatingExplanation } from './community-rating-explanation'
import type { Player, Position } from './types'

function CatalogRow({
  player: p,
  me,
  position,
  refresh,
  setModal,
}: {
  player: Player
  me: Player
  position: Position
  refresh: () => Promise<void>
  setModal: (value: string) => void
}) {
  const entry = ratingEntry(useRatingDrafts(me.id), p.id, position)
  const own = p.my_ratings?.[position]
  const current = (entry.confirmed?.revision ?? -1) > (own?.revision ?? -1) ? entry.confirmed : own
  const draft = entry.draft
  const values = draft ?? {
    playerId: p.id,
    alias: p.alias,
    position,
    attack: ratingInput(current?.attack),
    defense: ratingInput(current?.defense),
    revision: current?.revision ?? 0,
  }
  const busy = Boolean(entry.saving)
  const [saved, setSaved] = useState(false)
  const [refreshError, setRefreshError] = useState('')
  const keeper = position === 'keeper'
  const average = p.ratings?.[position]
  const editable = p.id !== me.id && !p.shared_keeper
  const columns = keeper ? 4 : 7
  async function save() {
    if (await saveRatingDraft(me.id, p.id, position)) {
      setSaved(true)
      try {
        await refresh()
        setRefreshError('')
      } catch {
        setRefreshError('Оценка сохранена. Общие баллы пока не удалось обновить.')
      }
    }
  }
  function input(key: 'attack' | 'defense') {
    return (
      <input
        className="catalog-score"
        aria-label={`Моя ${key === 'attack' ? 'атака' : 'защита'}: ${p.alias}`}
        inputMode="decimal"
        type="text"
        placeholder="—"
        maxLength={4}
        value={values[key]}
        disabled={busy}
        onChange={(e) => {
          changeRatingDraft(me.id, { ...values, [key]: e.target.value })
          setSaved(false)
        }}
      />
    )
  }
  return (
    <Fragment>
      <tr className={`catalog-person ${draft ? 'rating-dirty' : ''}`}>
        <td className="catalog-name">
          <PlayerName playerId={p.id} alias={p.alias} />
          {p.id === me.id && <small className="muted">Это вы</small>}
          {p.shared_keeper && <small className="muted">Общая карточка</small>}
          {me.is_admin && p.guest && !p.shared_keeper && (
            <button
              className="catalog-link-guest"
              aria-label={`Связать гостя ${p.alias}`}
              onClick={() => setModal(`link:${p.id}`)}
            >
              <ArrowUpRight size={12} /> Связать
            </button>
          )}
        </td>
        {!keeper && <td className="catalog-average">{ratingNumber(average?.attack ?? null)}</td>}
        <td className="catalog-average">{ratingNumber(average?.defense ?? null)}</td>
        {!keeper && (
          <td className="catalog-total">
            {average?.attack == null || average.defense == null
              ? '—'
              : ratingNumber(average.attack + average.defense)}
          </td>
        )}
        {!keeper && <td>{editable ? input('attack') : '—'}</td>}
        <td>{editable ? input('defense') : '—'}</td>
        <td>
          {editable && (
            <button
              className={`catalog-save ${saved ? 'saved' : ''}`}
              aria-label={`Сохранить оценки: ${p.alias}`}
              title={saved ? 'Оценки сохранены' : 'Сохранить оценки'}
              disabled={busy || !draft || entry.conflict !== undefined}
              onClick={() => void save()}
            >
              <Check size={16} />
            </button>
          )}
        </td>
      </tr>
      {(entry.error || saved || refreshError) && (
        <tr className="catalog-feedback">
          <td colSpan={columns}>
            <RatingDraftFeedback actor={me.id} player={p.id} position={position} />
            {saved && !draft && <span role="status">Оценки сохранены: {p.alias}</span>}
            {refreshError && <span role="status">{refreshError}</span>}
          </td>
        </tr>
      )}
    </Fragment>
  )
}

export function CatalogTable({
  players,
  me,
  position,
  refresh,
  setModal,
}: {
  players: Player[]
  me: Player
  position: Position
  refresh: () => Promise<void>
  setModal: (value: string) => void
}) {
  const keeper = position === 'keeper'
  return (
    <section className="panel catalog-table-panel">
      <div className="catalog-table-title">
        <h2>Каталог игроков</h2>
        <span className="muted">{players.length}</span>
      </div>
      <div className="table-scroll" tabIndex={0} role="region" aria-label="Таблица оценок игроков">
        <table className={`catalog-table ${keeper ? 'keeper-catalog' : ''}`}>
          <colgroup>
            <col className="catalog-name-col" />
            {!keeper && <col className="catalog-average-col" />}
            <col className="catalog-average-col" />
            {!keeper && <col className="catalog-average-col" />}
            {!keeper && <col className="catalog-own-col" />}
            <col className="catalog-own-col" />
            <col className="catalog-save-col" />
          </colgroup>
          <thead>
            <tr>
              <th rowSpan={2} scope="col">
                Игрок
              </th>
              <th colSpan={keeper ? 1 : 3} scope="colgroup">
                Средние оценки
              </th>
              <th colSpan={keeper ? 1 : 2} scope="colgroup">
                Мои оценки
              </th>
              <th rowSpan={2} scope="col">
                <span className="sr-only">Сохранить</span>
              </th>
            </tr>
            <tr>
              {!keeper && (
                <th scope="col">
                  <RatingMark kind="attack" />
                </th>
              )}
              <th scope="col">
                <RatingMark kind="defense" />
              </th>
              {!keeper && <th scope="col">Σ</th>}
              {!keeper && (
                <th scope="col">
                  <RatingMark kind="attack" />
                </th>
              )}
              <th scope="col">
                <RatingMark kind="defense" />
              </th>
            </tr>
          </thead>
          <tbody>
            {players.map((p) => (
              <CatalogRow
                key={`${p.id}:${position}`}
                player={p}
                me={me}
                position={position}
                refresh={refresh}
                setModal={setModal}
              />
            ))}
          </tbody>
        </table>
        {!players.length && <p className="empty-small muted">Игроки не найдены.</p>}
      </div>
      <p className="table-footnote">
        А — атака, З — защита. Оценки от 0 до 5.
        <br />
        Измените свои оценки и нажмите ✓ в строке игрока.
      </p>
      <CommunityRatingExplanation />
    </section>
  )
}
