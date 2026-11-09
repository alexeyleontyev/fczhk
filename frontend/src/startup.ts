function isTelegramLaunch() {
  const params = new URLSearchParams(location.hash.slice(1))
  if (
    window.Telegram?.WebApp ||
    params.has('tgWebAppData') ||
    params.has('tgWebAppPlatform') ||
    params.has('tgWebAppVersion') ||
    'TelegramWebviewProxy' in window
  )
    return true
  // Telegram can restore launch parameters from this tab after a reload.
  try {
    return Boolean(
      JSON.parse(sessionStorage.getItem('__telegram__initParams') || 'null')?.tgWebAppData,
    )
  } catch {
    return false
  }
}

async function prepareTelegram() {
  if (!isTelegramLaunch()) return
  if (!window.Telegram?.WebApp) {
    // A pending script delays window.load. Let Telegram reveal the local
    // splash even when its external SDK host is unreachable.
    if (document.readyState !== 'complete') {
      await new Promise<void>((resolve) =>
        window.addEventListener('load', () => resolve(), { once: true }),
      )
    }
    await new Promise<void>((resolve, reject) => {
      const script = document.createElement('script')
      script.src = 'https://telegram.org/js/telegram-web-app.js'
      script.onload = () => resolve()
      script.onerror = () =>
        reject(new Error('Не удалось загрузить Telegram. Проверьте подключение.'))
      document.head.appendChild(script)
    })
  }
  const app = window.Telegram?.WebApp
  if (!app) throw new Error('Не удалось запустить Telegram. Откройте приложение заново.')
  app.ready()
  app.expand()
}

// Navigation reads the Telegram start parameter during the first React render.
Promise.all([prepareTelegram(), import('./main')])
  .then(([, app]) => app.mount())
  .catch((error) => {
    console.error(error)
    window.clubLaunch.fail(
      error instanceof Error && error.message.startsWith('Не удалось')
        ? error.message
        : 'Не удалось загрузить приложение. Проверьте подключение.',
    )
  })
