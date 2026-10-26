import { useState, type FormEvent } from 'react'
import { Plus } from 'lucide-react'
import { Button } from './ui'
import { time } from './format'
import type { Match, Template, Player, Position } from './types'

const weekdays = ['Понедельник', 'Вторник', 'Среда', 'Четверг', 'Пятница', 'Суббота', 'Воскресенье']

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
          season: String(f.get('season') || '').trim() || null,
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
        Сезон
        <input
          name="season"
          defaultValue={match?.season || ''}
          maxLength={40}
          placeholder="По году даты игры"
        />
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
          opening_weekday: Number(f.get('opening_weekday')),
          opening_time: String(f.get('opening_time')),
          game_weekday: Number(f.get('game_weekday')),
          start_time: String(f.get('start_time')),
          location: String(f.get('location')),
          description: String(f.get('description')),
          payment_details: String(f.get('payment_details')),
          cost: Math.round(Number(f.get('cost')) * 100),
          announcements_chat_id: String(f.get('announcements_chat_id')).trim(),
          extended_chat_id: String(f.get('extended_chat_id')).trim(),
          extended_auction_enabled: f.has('extended_auction_enabled'),
          extended_registration_enabled: f.has('extended_registration_enabled'),
          extended_cancellation_enabled: f.has('extended_cancellation_enabled'),
          announcement_enabled: f.has('announcement_enabled'),
          announcement_minutes: Number(f.get('announcement_minutes')),
          payment_reminder_enabled: f.has('payment_reminder_enabled'),
          payment_reminder_weekday: Number(f.get('payment_reminder_weekday')),
          payment_reminder_time: String(f.get('payment_reminder_time')),
        })
      }}
    >
      <label className="checkbox">
        <input type="checkbox" name="enabled" defaultChecked={t.enabled} /> Автоматически открывать
        сбор
      </label>
      <label>
        День открытия сбора
        <select name="opening_weekday" defaultValue={t.opening_weekday} required>
          {weekdays.map((day, i) => (
            <option key={i} value={i}>
              {day}
            </option>
          ))}
        </select>
      </label>
      <label>
        Время открытия сбора · Москва
        <input name="opening_time" type="time" defaultValue={t.opening_time} required />
      </label>
      <label>
        День игры
        <select name="game_weekday" defaultValue={t.game_weekday} required>
          {weekdays.map((day, i) => (
            <option key={i} value={i}>
              {day}
            </option>
          ))}
        </select>
      </label>
      <label>
        Время игры · Москва
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
      <details className="compact-explanation notification-settings">
        <summary>Анонсы и напоминание об оплате</summary>
        <label>
          Чат анонсов
          <input
            name="announcements_chat_id"
            defaultValue={t.announcements_chat_id}
            placeholder="-1001234567890 или @channel"
            maxLength={100}
          />
        </label>
        <label className="checkbox">
          <input
            type="checkbox"
            name="announcement_enabled"
            defaultChecked={t.announcement_enabled}
          />
          Анонс перед открытием сбора
        </label>
        <label>
          За сколько минут до открытия
          <input
            name="announcement_minutes"
            type="number"
            min="1"
            max="10080"
            step="1"
            defaultValue={t.announcement_minutes}
            required
          />
        </label>
        <label className="checkbox">
          <input
            type="checkbox"
            name="payment_reminder_enabled"
            defaultChecked={t.payment_reminder_enabled}
          />
          Напоминать об оплате футбола
        </label>
        <label>
          День напоминания об оплате
          <select name="payment_reminder_weekday" defaultValue={t.payment_reminder_weekday}>
            {weekdays.map((day, i) => (
              <option key={i} value={i}>
                {day}
              </option>
            ))}
          </select>
        </label>
        <label>
          Время напоминания об оплате · Москва
          <input
            name="payment_reminder_time"
            type="time"
            defaultValue={t.payment_reminder_time}
            required
          />
        </label>
        <p className="muted caption">
          Анонс следует расписанию автосбора. Напоминание об оплате приходит один раз на игру, после
          открытия и до её начала.
        </p>
      </details>
      <details className="compact-explanation notification-settings">
        <summary>Расширенный чат и типы сообщений</summary>
        <label>
          Чат расширенных уведомлений
          <input
            name="extended_chat_id"
            defaultValue={t.extended_chat_id}
            placeholder="-1001234567890 или @channel"
            maxLength={100}
          />
        </label>
        <label className="checkbox">
          <input
            type="checkbox"
            name="extended_auction_enabled"
            defaultChecked={t.extended_auction_enabled}
          />{' '}
          Аукцион
        </label>
        <label className="checkbox">
          <input
            type="checkbox"
            name="extended_registration_enabled"
            defaultChecked={t.extended_registration_enabled}
          />{' '}
          Записи на игру
        </label>
        <label className="checkbox">
          <input
            type="checkbox"
            name="extended_cancellation_enabled"
            defaultChecked={t.extended_cancellation_enabled}
          />{' '}
          Отмены записей
        </label>
        <p className="muted caption">
          Без указанного чата подробные уведомления не отправляются. Бот должен иметь право
          публиковать сообщения.
        </p>
      </details>
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
  const [playerId, setPlayerId] = useState('')
  const sharedKeeper = Boolean(players.find((p) => p.id === Number(playerId))?.shared_keeper)
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
        {m.status === 'draft' && m.scheduled_opening_at
          ? 'Игрок попадёт в начало очереди после открытия сбора. Подтверждение оплаты требуется по общим правилам.'
          : 'Прямое включение администратором. При заполненном составе выберите, кого заменить.'}
      </p>
      <label>
        Игрок
        <select
          name="player"
          required
          value={playerId}
          onChange={(e) => {
            setPlayerId(e.target.value)
            if (players.find((p) => p.id === Number(e.target.value))?.shared_keeper) {
              setPosition('keeper')
            }
          }}
        >
          <option value="">Выберите из каталога</option>
          {players
            .filter(
              (p) =>
                !m.registrations.some(
                  (r) =>
                    r.player_id === p.id &&
                    ((m.status === 'draft' && m.scheduled_opening_at) || r.selected || r.forced),
                ),
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
        <select
          value={position}
          disabled={sharedKeeper}
          onChange={(e) => setPosition(e.target.value as Position)}
        >
          <option value="field">Полевой</option>
          <option value="keeper">Вратарь</option>
        </select>
      </label>
      {!(m.status === 'draft' && m.scheduled_opening_at) && (
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
      )}
      <Button disabled={busy} type="submit">
        {m.status === 'draft' && m.scheduled_opening_at ? 'Записать заранее' : 'Добавить в состав'}
      </Button>
    </form>
  )
}
