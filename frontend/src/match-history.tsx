import { date, time } from './format'
import type { History } from './types'
import type { ReactNode } from 'react'
import { PlayerName } from './player-name'

const titles: Record<string, string> = {
  'history.imported': 'Импортирована игра',
  'match.archive_details_edited': 'Изменены параметры игры',
  'match.edited': 'Изменены параметры игры',
  'result.completed': 'Сохранён результат',
  'result.draft_saved': 'Сохранён черновик результата',
  'match.created': 'Создана игра',
  'match.opened': 'Открыт сбор',
  'match.finalized': 'Зафиксирован список участников',
  'match.cancelled': 'Игра отменена',
  'collection.closed': 'Сбор закрыт, дата игры сохранена',
  'collection.image_changed': 'Сохранена картинка к посту открытия',
  'collection.image_removed': 'Картинка убрана из поста открытия',
  'teams.saved': 'Изменены составы',
  'teams.approved': 'Утверждены составы',
  'match.approved': 'Утверждены составы',
  'lineup.confirmed': 'Утверждены составы',
  'lineup.shared': 'Опубликован вариант состава',
  'auction.started': 'Начат аукцион',
  'auction.completed': 'Завершён аукцион',
  'auction.lot_resolved': 'Разыгран игрок на аукционе',
  'auction.invalidated': 'Аукцион сброшен после изменения списка',
  'auction.pause': 'Аукцион приостановлен',
  'auction.resume': 'Аукцион продолжен',
  'auction.cancel': 'Аукцион отменён',
  'registration.created': 'Игрок записался на игру',
  'registration.joined': 'Игрок записался на игру',
  'registration.cancelled': 'Игрок отменил запись',
  'participant.added': 'Добавлен участник',
  'payment.confirmed': 'Подтверждена оплата',
  'payment.changed': 'Изменена отметка оплаты',
  'reserve.promoted': 'Игрок переведён из резерва',
  'teams.colors_swapped': 'Поменяны цвета команд',
  'teams.publication_requested': 'Запрошена публикация составов',
  'rating.temporary_saved': 'Изменена оценка на игру',
  'balance.applied': 'Применён вариант составов',
}
const object = (value: unknown): Record<string, unknown> =>
  value !== null && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {}
const fullDate = (value: unknown) =>
  typeof value === 'string'
    ? new Date(value).toLocaleDateString('ru-RU', {
        day: 'numeric',
        month: 'long',
        year: 'numeric',
        timeZone: 'Europe/Moscow',
      })
    : 'Не указано'
const resultScore = (value: unknown) => {
  const row = object(value)
  return typeof row.white === 'number' && typeof row.black === 'number'
    ? `${row.white} : ${row.black}`
    : 'Не указан'
}

function changes(row: History['audit'][number]): string[] {
  const data = object(row.data),
    old = object(data.old),
    next = object(data.new)
  if (row.action === 'history.imported') return ['Сохранены составы, счёт и голы из источника.']
  if (row.action.startsWith('result.')) {
    const result = [`Счёт: ${resultScore(old.score)} → ${resultScore(next.score)}`]
    if (JSON.stringify(old.participants) !== JSON.stringify(next.participants))
      result.push('Уточнены фактические составы.')
    if (JSON.stringify(old.goals) !== JSON.stringify(next.goals))
      result.push('Обновлены голы и передачи.')
    return result
  }
  if (row.action === 'match.archive_details_edited' || row.action === 'match.edited') {
    const result = []
    if (old.game_day !== next.game_day || (!old.game_day && old.starts_at !== next.starts_at)) {
      result.push(
        `Дата: ${fullDate(old.game_day || old.starts_at)} → ${fullDate(next.game_day || next.starts_at)}`,
      )
    }
    const oldTime =
      old.time_known === false
        ? 'Не указано'
        : typeof old.starts_at === 'string'
          ? time(old.starts_at)
          : 'Не указано'
    const nextTime =
      next.time_known === false
        ? 'Не указано'
        : typeof next.starts_at === 'string'
          ? time(next.starts_at)
          : 'Не указано'
    if (oldTime !== nextTime) result.push(`Время: ${oldTime} → ${nextTime}`)
    const place = (value: unknown) =>
      !value || value === 'Не указано в историческом источнике' ? 'Не указано' : String(value)
    if (old.location !== next.location)
      result.push(`Место: ${place(old.location)} → ${place(next.location)}`)
    if (old.season !== next.season)
      result.push(
        `Сезон: ${String(old.season || 'Не указан')} → ${String(next.season || 'Не указан')}`,
      )
    return result.length ? result : ['Параметры игры сохранены.']
  }
  return []
}

function resultChanges(row: History['audit'][number]): ReactNode[] {
  if (!row.action.startsWith('result.')) return []
  const data = object(row.data),
    old = object(data.old),
    next = object(data.new)
  const records = (value: unknown) => (Array.isArray(value) ? value.map(object) : [])
  const oldPeople = records(old.participants),
    nextPeople = records(next.participants)
  const allPeople = [...oldPeople, ...nextPeople]
  const name = (id: unknown) =>
    String(allPeople.find((p) => p.player_id === id)?.alias || 'Автор неизвестен')
  const personName = (person: Record<string, unknown>) => (
    <PlayerName
      playerId={typeof person.player_id === 'number' ? person.player_id : undefined}
      alias={String(person.alias || 'Автор неизвестен')}
    />
  )
  const linkedName = (id: unknown) => (
    <PlayerName playerId={typeof id === 'number' ? id : undefined} alias={name(id)} />
  )
  const side = (value: unknown) => (value === 'white' ? 'Белые' : 'Чёрные')
  const position = (person: Record<string, unknown>) =>
    `${side(person.team)}, ${person.position === 'keeper' ? 'вратарь' : 'полевой'}`
  const goal = (value: Record<string, unknown>) =>
    `${side(value.team)} · ${value.kind === 'own_goal' ? 'автогол' + (value.author_id ? ` (${name(value.author_id)})` : '') : name(value.author_id)}${value.assist_id ? `, пас: ${name(value.assist_id)}` : ''}`
  const linkedGoal = (value: Record<string, unknown>) => (
    <>
      {side(value.team)} ·{' '}
      {value.kind === 'own_goal' ? (
        <>автогол{Boolean(value.author_id) && <> ({linkedName(value.author_id)})</>}</>
      ) : (
        linkedName(value.author_id)
      )}
      {Boolean(value.assist_id) && <>, пас: {linkedName(value.assist_id)}</>}
    </>
  )
  const lines: ReactNode[] = []
  for (const person of nextPeople) {
    const before = oldPeople.find((p) => p.player_id === person.player_id)
    if (!before)
      lines.push(
        <>
          Добавлен участник: {personName(person)} · {position(person)}
        </>,
      )
    else if (before.team !== person.team || before.position !== person.position)
      lines.push(
        <>
          {personName(person)}: {position(before)} → {position(person)}
        </>,
      )
  }
  for (const person of oldPeople) {
    if (!nextPeople.some((p) => p.player_id === person.player_id))
      lines.push(
        <>
          Убран участник: {personName(person)} · {position(person)}
        </>,
      )
  }
  const oldGoals = records(old.goals),
    nextGoals = records(next.goals)
  nextGoals.forEach((event, index) => {
    const before = oldGoals.find((g) => g.id === event.id)
    if (!before)
      lines.push(
        <>
          Добавлен гол {index + 1}: {linkedGoal(event)}
        </>,
      )
    else if (goal(before) !== goal(event))
      lines.push(
        <>
          Гол {index + 1}: {linkedGoal(before)} → {linkedGoal(event)}
        </>,
      )
  })
  oldGoals.forEach((event, index) => {
    if (!nextGoals.some((g) => g.id === event.id))
      lines.push(
        <>
          Удалён гол {index + 1}: {linkedGoal(event)}
        </>,
      )
  })
  return lines
}

export function MatchHistory({ history }: { history: History }) {
  return (
    <div className="match-history">
      {!history.audit.length && !history.teams.length && (
        <p className="muted">Изменений пока нет.</p>
      )}
      {history.audit.map((row) => (
        <div className="history-row" key={row.id}>
          <strong>{titles[row.action] || 'Изменение игры'}</strong>
          {changes(row).map((line, index) => (
            <p key={index}>{line}</p>
          ))}
          {resultChanges(row).length > 0 && (
            <details>
              <summary>Подробности изменений</summary>
              <ul>
                {resultChanges(row).map((line, index) => (
                  <li key={index}>{line}</li>
                ))}
              </ul>
            </details>
          )}
          <small>
            {fullDate(row.at)}, {time(row.at)} ·{' '}
            <PlayerName playerId={row.actor_id} alias={row.actor || 'Система'} />
          </small>
        </div>
      ))}
      {history.teams.map((team) => (
        <details key={team.version}>
          <summary>
            Состав версии {team.version} · {date(team.at)}
          </summary>
          {team.teams.map((person, index) => (
            <p key={index}>
              {person.team === 'white' ? '⚪' : '⚫'}{' '}
              <PlayerName playerId={person.player_id} alias={person.alias} />
            </p>
          ))}
        </details>
      ))}
    </div>
  )
}
