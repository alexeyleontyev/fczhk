import { Fragment, useState } from 'react'
import { ArrowUpRight, Check } from 'lucide-react'
import { api, ApiError } from './api'
import { PlayerName } from './player-name'
import { RatingMark, ratingNumber } from './rating-mark'
import type { OwnRating, Player, Position } from './types'

type Draft = { attack: string; defense: string; revision: number }
const inputValue = (value: number | null | undefined) =>
  value == null ? '' : String(value).replace('.', ',')
function initial(player: Player, position: Position): Draft {
  const own = player.my_ratings?.[position]
  return {
    attack: inputValue(own?.attack),
    defense: inputValue(own?.defense),
    revision: own?.revision ?? 0,
  }
}

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
  const [draft, setDraft] = useState<Draft | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [conflict, setConflict] = useState(false)
  const [saved, setSaved] = useState(false)
  const values = draft ?? initial(p, position)
  const keeper = position === 'keeper'
  const average = p.ratings?.[position]
  const editable = p.id !== me.id && !p.shared_keeper
  const columns = keeper ? 4 : 7
  async function save() {
    if (busy || !draft) return
    const valid = (value: string) =>
      /^[0-5]([.,][0-9])?$/.test(value.trim()) && Number(value.replace(',', '.')) <= 5
    if (!valid(values.defense) || (!keeper && !valid(values.attack))) {
      setError('Введите оценки от 0 до 5 с шагом 0,1.')
      return
    }
    setBusy(true)
    setError('')
    setConflict(false)
    setSaved(false)
    try {
      const data = await api<{ own: OwnRating }>(`/players/${p.id}/ratings`, 'PUT', {
        position,
        attack: keeper ? null : values.attack.trim(),
        defense: values.defense.trim(),
        revision: values.revision,
      })
      setDraft({
        attack: inputValue(data.own.attack),
        defense: inputValue(data.own.defense),
        revision: data.own.revision,
      })
      setSaved(true)
      await refresh()
      setDraft(null)
    } catch (e) {
      setError((e as Error).message)
      setConflict(e instanceof ApiError && e.status === 409)
    } finally {
      setBusy(false)
    }
  }
  async function reload() {
    setBusy(true)
    try {
      await refresh()
      setDraft(null)
      setError('')
      setConflict(false)
      setSaved(false)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
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
          setDraft({ ...values, [key]: e.target.value })
          setSaved(false)
          if (!conflict) setError('')
        }}
      />
    )
  }
  return (
    <Fragment>
      <tr className={`catalog-person ${draft && !saved ? 'rating-dirty' : ''}`}>
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
              disabled={busy || !draft || saved || conflict}
              onClick={() => void save()}
            >
              <Check size={16} />
            </button>
          )}
        </td>
      </tr>
      {(error || saved) && (
        <tr className="catalog-feedback">
          <td colSpan={columns}>
            {error ? (
              <span role="alert">
                {error}{' '}
                {conflict && (
                  <button className="text-button" disabled={busy} onClick={() => void reload()}>
                    Загрузить актуальные оценки
                  </button>
                )}
              </span>
            ) : (
              <span role="status">Оценки сохранены: {p.alias}</span>
            )}
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
    </section>
  )
}
