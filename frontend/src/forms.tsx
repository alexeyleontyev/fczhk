import { useState, type FormEvent } from 'react'
import { Plus } from 'lucide-react'
import { Button } from './ui'
import { time } from './format'
import type { Match, Template, Player, Position } from './types'

export function GameForm({
  match,
  template,
  busy,
  save,
}: {
  match?: Match
  template?: Template | null
  busy: boolean
  save: (data: object) => Promise<void>
}) {
  const dateValue = match ? `${match.game_day}T${time(match.starts_at)}` : ''
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault()
        const f = new FormData(e.currentTarget)
        void save({
          starts_at: `${f.get('starts_at')}:00+03:00`,
          location: f.get('location'),
          description: f.get('description'),
          payment_details: f.get('payment_details'),
          cost: Math.round(Number(f.get('cost')) * 100),
        })
      }}
    >
      <label>
        Дата и время · Москва
        <input name="starts_at" type="datetime-local" defaultValue={dateValue} required />
      </label>
      <label>
        Место игры
        <input
          name="location"
          defaultValue={match?.location || template?.location}
          required
          minLength={2}
          maxLength={200}
        />
      </label>
      <label>
        Стоимость, ₽
        <input
          name="cost"
          type="number"
          min="0"
          step="0.01"
          max="1000000"
          defaultValue={(match?.cost ?? template?.cost ?? 0) / 100}
          required
        />
      </label>
      <label>
        Куда переводить
        <textarea
          name="payment_details"
          defaultValue={match?.payment_details || template?.payment_details}
          maxLength={500}
        />
      </label>
      <label>
        Описание
        <textarea
          name="description"
          defaultValue={match?.description || template?.description}
          maxLength={1500}
        />
      </label>
      <Button type="submit" disabled={busy}>
        {match ? 'Сохранить параметры' : 'Создать черновик'}
      </Button>
    </form>
  )
}

export function TemplateForm({
  template: t,
  busy,
  save,
}: {
  template: Template
  busy: boolean
  save: (data: Template) => Promise<void>
}) {
  return (
    <form
      key={t.version}
      onSubmit={(e) => {
        e.preventDefault()
        const f = new FormData(e.currentTarget)
        void save({
          version: t.version,
          enabled: f.has('enabled'),
          start_time: String(f.get('start_time')),
          location: String(f.get('location')),
          description: String(f.get('description')),
          payment_details: String(f.get('payment_details')),
          cost: Math.round(Number(f.get('cost')) * 100),
        })
      }}
    >
      <label className="checkbox">
        <input type="checkbox" name="enabled" defaultChecked={t.enabled} /> Автоматически открывать
        сбор по вторникам
      </label>
      <label>
        Время игры в пятницу · Москва
        <input name="start_time" type="time" defaultValue={t.start_time} required />
      </label>
      <label>
        Место
        <input name="location" defaultValue={t.location} maxLength={200} />
      </label>
      <label>
        Стоимость, ₽
        <input name="cost" type="number" min="0" step="0.01" defaultValue={t.cost / 100} />
      </label>
      <label>
        Куда переводить
        <textarea name="payment_details" defaultValue={t.payment_details} maxLength={500} />
      </label>
      <label>
        Описание
        <textarea name="description" defaultValue={t.description} maxLength={1500} />
      </label>
      <Button type="submit" disabled={busy}>
        Сохранить шаблон
      </Button>
    </form>
  )
}

export function IncludeForm({
  match: m,
  players,
  busy,
  save,
  newGuest,
}: {
  match: Match
  players: Player[]
  busy: boolean
  save: (data: object) => Promise<void>
  newGuest: () => void
}) {
  const [position, setPosition] = useState<Position>('field')
  return (
    <form
      onSubmit={(e: FormEvent<HTMLFormElement>) => {
        e.preventDefault()
        const f = new FormData(e.currentTarget)
        void save({
          player_id: Number(f.get('player')),
          position,
          replace_id: f.get('replace') ? Number(f.get('replace')) : null,
        })
      }}
    >
      <p className="muted">
        Прямое включение администратором. При заполненном составе выберите, кого заменить.
      </p>
      <label>
        Игрок
        <select name="player" required>
          <option value="">Выберите из каталога</option>
          {players
            .filter(
              (p) => !m.registrations.some((r) => r.player_id === p.id && (r.selected || r.forced)),
            )
            .map((p) => (
              <option key={p.id} value={p.id}>
                {p.alias}
                {p.guest ? ' · гость' : ''}
              </option>
            ))}
        </select>
      </label>
      <Button className="ghost compact" onClick={newGuest}>
        <Plus size={15} /> Создать нового гостя
      </Button>
      <label>
        Амплуа
        <select value={position} onChange={(e) => setPosition(e.target.value as Position)}>
          <option value="field">Полевой</option>
          <option value="keeper">Вратарь</option>
        </select>
      </label>
      <label>
        Кого заменить
        <select name="replace" key={position}>
          <option value="">Без замены — если есть место</option>
          {m.registrations
            .filter((r) => r.selected && r.position === position)
            .map((r) => (
              <option key={r.id} value={r.id}>
                {r.alias}
              </option>
            ))}
        </select>
      </label>
      <Button disabled={busy} type="submit">
        Добавить в состав
      </Button>
    </form>
  )
}
