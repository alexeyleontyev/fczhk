import { expect, test } from '@playwright/test'

test('signals Telegram ready before waiting for the server, even without session storage', async ({
  page,
}) => {
  await page.route('https://telegram.org/js/telegram-web-app.js', (route) => route.abort())
  await page.addInitScript(() => {
    Object.defineProperty(window, 'sessionStorage', {
      get: () => {
        throw new Error('Storage denied')
      },
    })
    Object.assign(window, {
      Telegram: {
        WebApp: {
          initData: '',
          ready: () => {
            document.documentElement.dataset.telegramReady = 'yes'
          },
          expand: () => {},
        },
      },
    })
  })
  let releaseHealth!: () => void
  const healthGate = new Promise<void>((resolve) => {
    releaseHealth = resolve
  })
  await page.route('**/api/health', async (route) => {
    await healthGate
    await route.continue()
  })
  await page.goto('/')
  try {
    await expect(page.locator('html')).toHaveAttribute('data-telegram-ready', 'yes')
    await expect(page.getByText('Открываем клуб…')).toBeVisible()
  } finally {
    releaseHealth()
  }
  await expect(page.getByText('Локальная демонстрация')).toBeVisible()
})

test('a late SDK completes login in memory and opens the screen in the Telegram link', async ({
  page,
}) => {
  const { token } = await (await page.request.post('/api/auth/demo/player')).json()
  const match = await (
    await page.request.get('/api/matches/current', {
      headers: { Authorization: 'Bearer ' + token },
    })
  ).json()
  let release!: () => void
  const gate = new Promise<void>((done) => {
    release = done
  })
  await page.addInitScript(() => {
    Object.defineProperty(window, 'sessionStorage', {
      get() {
        throw new Error('blocked')
      },
    })
  })
  await page.route('**/telegram-web-app.js', async (route) => {
    await gate
    await route.fulfill({
      contentType: 'application/javascript',
      body: `window.Telegram = {WebApp:{initData:'signed-test',initDataUnsafe:{start_param:'game_${match.id}_auction'},ready(){},expand(){}}}`,
    })
  })
  let logins = 0
  await page.route('**/api/auth/telegram', async (route) => {
    expect(route.request().postDataJSON()).toEqual({ init_data: 'signed-test' })
    logins++
    await route.fulfill({ json: { token } })
  })
  await page.goto('/#tgWebAppData=test', { waitUntil: 'domcontentloaded' })
  try {
    await page.waitForLoadState('load', { timeout: 4000 })
    await expect(page.getByText('Загрузка занимает больше времени…')).toBeVisible({ timeout: 9000 })
    await expect(page.getByRole('button', { name: 'Повторить', exact: true })).toBeVisible()
  } finally {
    release()
  }
  await expect(page.getByRole('heading', { name: 'Аукцион капитанов', exact: true })).toBeVisible()
  expect(logins).toBe(1)
})

test('failed SDK download can be retried on the same launch link', async ({ page }) => {
  let attempts = 0
  await page.route('**/telegram-web-app.js', (route) => {
    if (++attempts === 1) return route.abort()
    return route.fulfill({
      contentType: 'application/javascript',
      body: 'window.Telegram={WebApp:{ready(){},expand(){}}}',
    })
  })
  await page.goto('/#tgWebAppPlatform=android')
  await expect(
    page.getByText('Не удалось загрузить Telegram. Проверьте подключение.'),
  ).toBeVisible()
  await page.getByRole('button', { name: 'Повторить', exact: true }).click()
  await expect(page.getByText('Локальная демонстрация')).toBeVisible()
  expect(attempts).toBe(2)
})

test('the HTML offers recovery when the application bundle fails', async ({ page }) => {
  await page.route('**/assets/main-*.js', (route) => route.abort())
  await page.goto('/')
  await expect(page.getByRole('button', { name: 'Повторить', exact: true })).toBeVisible()
  await expect(
    page.getByText('Не удалось загрузить приложение. Проверьте подключение.'),
  ).toBeVisible()
})

test('an uncaught render error leaves a working reload button', async ({ page }) => {
  await page.addInitScript(() => {
    if (sessionStorage.getItem('render-retried')) return
    sessionStorage.setItem('render-retried', '1')
    window.Telegram = {
      WebApp: {
        initData: 'test',
        ready() {},
        expand() {},
        isVersionAtLeast() {
          throw new Error('simulated WebView failure during render')
        },
      },
    }
  })
  await page.goto('/')
  await expect(page.getByText('Не удалось открыть приложение. Попробуйте ещё раз.')).toBeVisible()
  await page.getByRole('button', { name: 'Повторить', exact: true }).click()
  await expect(page.getByText('Локальная демонстрация')).toBeVisible()
})
