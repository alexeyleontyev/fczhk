export const date = (s: string) =>
  new Date(s).toLocaleDateString('ru-RU', {
    day: 'numeric',
    month: 'long',
    timeZone: 'Europe/Moscow',
  })
export const time = (s: string) =>
  new Date(s).toLocaleTimeString('ru-RU', {
    hour: '2-digit',
    minute: '2-digit',
    timeZone: 'Europe/Moscow',
  })
export const money = (n: number) => (n / 100).toLocaleString('ru-RU') + ' ₽'
export const publicationKind: Record<string, string> = {
  collection: 'Сбор',
  teams: 'Составы',
  cancellation: 'Отмена игры',
  auction_start: 'Старт аукциона',
  auction_lot: 'Аукцион',
  result: 'Итог игры',
  opening_notice: 'Анонс открытия',
  payment_notice: 'Напоминание об оплате',
  registration: 'Запись на игру',
  withdrawal: 'Отмена записи',
}
export const status = {
  draft: 'Черновик',
  open: 'Запись открыта',
  finalized: 'Сбор завершен',
  approved: 'Команды готовы',
  completed: 'Матч завершён',
  cancelled: 'Игра отменена',
}
export const initial = (name: string) =>
  name
    .split(' ')
    .map((x) => x[0])
    .slice(0, 2)
    .join('')
