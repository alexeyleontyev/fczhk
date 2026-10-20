import type { TelegramProfile } from './types'

export function TelegramIdentity({ telegram_id, telegram_username }: TelegramProfile) {
  if (!telegram_id) return null
  return (
    <p className="muted caption telegram-identity" aria-label="Аккаунт Telegram">
      {telegram_username ? (
        <a href={`https://t.me/${telegram_username}`} target="_blank" rel="noreferrer">
          @{telegram_username}
        </a>
      ) : (
        `Telegram ID: ${telegram_id}`
      )}
    </p>
  )
}
