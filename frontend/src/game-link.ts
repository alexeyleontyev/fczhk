export function requestedGame() {
  const query = new URLSearchParams(location.search)
  const start = window.Telegram?.WebApp?.initDataUnsafe?.start_param?.match(
    /^game_(\d+)(?:_(auction|lineup|prediction))?$/,
  )
  const id = Number(start?.[1] ?? query.get('game'))
  const screen = start?.[2] ?? query.get('screen')
  return {
    id: Number.isInteger(id) && id > 0 ? id : null,
    screen: ['auction', 'lineup', 'prediction'].includes(screen ?? '') ? screen! : 'game',
  }
}
