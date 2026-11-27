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
  auction_open: 'Новый лот аукциона',
  auction_lot: 'Аукцион',
  result: 'Итог игры',
  opening_notice: 'Анонс открытия',
  payment_notice: 'Напоминание об оплате',
  roster_full: 'Состав набран',
  roster_full_ch: 'Состав набран в канале',
  roster_reported: 'Все отметили оплату',
  roster_closed: 'Набор окончен',
  roster_close_ch: 'Набор окончен в канале',
  roster_notice_2: 'Напоминание о наборе за 2 дня',
  roster_notice_1: 'Напоминание о наборе за день',
  lineup_share: 'Вариант состава',
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
