import { useSyncExternalStore } from 'react'
import { api, ApiError, sessionVersion } from './api'
import type { OwnRating, Position } from './types'

export type RatingDraft = {
  playerId: number
  alias: string
  position: Position
  attack: string
  defense: string
  revision: number
}
type Entry = {
  draft?: RatingDraft
  confirmed?: OwnRating
  saving?: boolean
  error?: string
  conflict?: OwnRating | null
}
type State = Record<string, Entry>
const stores = new Map<number, State>()
const listeners = new Set<() => void>()
const key = (player: number, position: Position) => `${player}:${position}`
const storageKey = (actor: number) => `fczhk-rating-drafts-v1:${actor}`
function state(actor: number): State {
  if (!stores.has(actor)) {
    const loaded: State = {}
    try {
      const drafts: unknown = JSON.parse(localStorage.getItem(storageKey(actor)) || '[]')
      if (Array.isArray(drafts))
        for (const d of drafts) {
          if (
            d &&
            Number.isInteger(d.playerId) &&
            d.playerId > 0 &&
            ['field', 'keeper'].includes(d.position) &&
            typeof d.alias === 'string' &&
            typeof d.attack === 'string' &&
            typeof d.defense === 'string' &&
            Number.isInteger(d.revision) &&
            d.revision >= 0
          )
            loaded[key(d.playerId, d.position)] = { draft: d }
        }
    } catch {
      /* Keep in-memory drafts when browser storage is unavailable. */
    }
    stores.set(actor, loaded)
  }
  return stores.get(actor)!
}
function update(actor: number, id: string, entry: Entry) {
  const next = { ...state(actor), [id]: entry }
  stores.set(actor, next)
  try {
    localStorage.setItem(
      storageKey(actor),
      JSON.stringify(Object.values(next).flatMap((e) => (e.draft ? [e.draft] : []))),
    )
  } catch {
    /* Navigation still retains the in-memory draft. */
  }
  listeners.forEach((listener) => listener())
}
function subscribe(listener: () => void) {
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
  }
}
export function useRatingDrafts(actor: number) {
  return useSyncExternalStore(subscribe, () => state(actor))
}
export function ratingEntry(entries: State, player: number, position: Position): Entry {
  return entries[key(player, position)] ?? {}
}
export const ratingInput = (value: number | null | undefined) =>
  value == null ? '' : String(value).replace('.', ',')
export function changeRatingDraft(actor: number, draft: RatingDraft) {
  const id = key(draft.playerId, draft.position),
    entry = state(actor)[id] ?? {}
  if (entry.saving) return
  update(actor, id, {
    ...entry,
    draft,
    error: entry.conflict !== undefined ? entry.error : undefined,
  })
}
export function discardRatingDraft(actor: number, player: number, position: Position) {
  const id = key(player, position),
    entry = state(actor)[id] ?? {}
  if (!entry.saving) update(actor, id, { confirmed: entry.conflict ?? entry.confirmed })
}
export function acceptRatingRevision(actor: number, player: number, position: Position) {
  const id = key(player, position),
    entry = state(actor)[id]
  if (!entry?.draft || entry.conflict === undefined || entry.saving) return
  update(actor, id, {
    ...entry,
    draft: { ...entry.draft, revision: entry.conflict?.revision ?? 0 },
    confirmed: entry.conflict ?? undefined,
    conflict: undefined,
    error: undefined,
  })
}
export async function saveRatingDraft(
  actor: number,
  player: number,
  position: Position,
): Promise<boolean> {
  const id = key(player, position),
    entry = state(actor)[id],
    draft = entry?.draft
  if (!draft || entry.saving) return false
  const valid = (value: string) =>
    /^[0-5]([.,][0-9])?$/.test(value.trim()) && Number(value.replace(',', '.')) <= 5
  if (!valid(draft.defense) || (position === 'field' && !valid(draft.attack))) {
    update(actor, id, { ...entry, error: 'Введите оценки от 0 до 5 с шагом 0,1.' })
    return false
  }
  const session = sessionVersion()
  update(actor, id, { ...entry, saving: true, error: undefined, conflict: undefined })
  try {
    // Reconcile before every save: also resolves writes whose response was lost.
    const latest = await api<{ own: OwnRating | null }>(`/players/${player}/ratings/${position}`)
    if (session !== sessionVersion())
      throw new ApiError('Аккаунт изменился. Черновик остался у его автора.', 401)
    const same =
      latest.own &&
      latest.own.defense === Number(draft.defense.replace(',', '.')) &&
      (position === 'keeper' || latest.own.attack === Number(draft.attack.replace(',', '.')))
    if (same) {
      update(actor, id, { confirmed: latest.own! })
      return true
    }
    if ((latest.own?.revision ?? 0) !== draft.revision) {
      update(actor, id, {
        ...entry,
        conflict: latest.own,
        error:
          'Оценку изменили в другом окне. Ваш ввод сохранён. Сравните версии перед сохранением.',
      })
      return false
    }
    const result = await api<{ own: OwnRating }>(`/players/${player}/ratings`, 'PUT', {
      position,
      attack: position === 'keeper' ? null : draft.attack.trim(),
      defense: draft.defense.trim(),
      revision: draft.revision,
    })
    update(actor, id, { confirmed: result.own })
    return true
  } catch (e) {
    update(actor, id, {
      ...entry,
      error: e instanceof ApiError ? e.message : 'Не удалось сохранить оценку. Ваш ввод сохранён.',
    })
    return false
  }
}

export async function removeRating(
  actor: number,
  player: number,
  position: Position,
  revision: number,
  refresh: () => Promise<void>,
) {
  const id = key(player, position),
    entry = state(actor)[id] ?? {}
  if (entry.saving) return false
  update(actor, id, { ...entry, saving: true, error: undefined })
  try {
    const result = await api<{ own: OwnRating | null }>(
      `/players/${player}/ratings/${position}`,
      'DELETE',
      { revision },
    )
    update(actor, id, { confirmed: result.own ?? undefined })
    try {
      await refresh()
    } catch {
      update(actor, id, {
        ...state(actor)[id],
        error: 'Оценка удалена. Обновить общие баллы пока не удалось.',
      })
    }
    return true
  } catch (e) {
    update(actor, id, { ...entry, error: (e as Error).message })
    return false
  }
}
