import { expect, test, type Page } from '@playwright/test'

const sdk = `
window.Telegram = window.Telegram || {};
window.Telegram.Login = {
  auth(options, callback) {
    window.loginOptions = options;
    window.completeLogin = callback;
  },
  close() { window.completeLogin = null; }
};`

type LoginWindow = Window & {
  loginOptions: { client_id: number; nonce: string; scope: string[] }
  completeLogin: (result: { id_token?: string; error?: string }) => void
}

async function configure(page: Page) {
  // Use the disposable demo's real session for application API calls after login.
  const response = await page.request.post('/api/auth/demo/player')
  const { token } = await response.json()
  await page.route('**/api/health', async (route) => {
    await route.fulfill({ json: { status: 'ok', demo: false } })
  })
  await page.route('**/api/auth/options', async (route) => {
    await route.fulfill({
      json: { browser_login: true, bot_url: 'https://t.me/football_test_bot' },
    })
  })
  let challenges = 0
  await page.route('**/api/auth/telegram/browser/challenge', async (route) => {
    await route.fulfill({ json: { client_id: 123456, nonce: `challenge-${++challenges}` } })
  })
  await page.route('https://telegram.org/js/telegram-login.js', async (route) => {
    await route.fulfill({ contentType: 'application/javascript', body: sdk })
  })
  await page.route('**/api/auth/telegram/browser', async (route) => {
    expect(route.request().postDataJSON()).toEqual({ id_token: 'telegram-signed-token' })
    await route.fulfill({ json: { token } })
  })
  return token
}

async function complete(page: Page, result: { id_token?: string; error?: string }) {
  await page.evaluate((value) => (window as LoginWindow).completeLogin(value), result)
}

for (const viewport of [
  { width: 390, height: 844 },
  { width: 1440, height: 1050 },
]) {
  test(`browser Telegram login, session and game link at ${viewport.width}px`, async ({ page }) => {
    await page.setViewportSize(viewport)
    const token = await configure(page)
    const games = await page.request.get('/api/matches', {
      headers: { Authorization: `Bearer ${token}` },
    })
    const gameId = (await games.json()).find(
      (game: { status: string }) => game.status === 'open',
    ).id
    await page.goto(`/?game=${gameId}`)
    const login = page.getByRole('button', { name: 'Войти через Telegram', exact: true })
    await expect(login).toBeEnabled()
    await expect(page.getByRole('link', { name: 'Открыть Telegram-бота' })).toHaveAttribute(
      'href',
      'https://t.me/football_test_bot',
    )
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
    await page.screenshot({
      path: `test-results/browser-login-${viewport.width}.png`,
      fullPage: true,
    })
    await login.click()
    const options = await page.evaluate(() => (window as LoginWindow).loginOptions)
    expect(options).toEqual({
      client_id: 123456,
      nonce: 'challenge-1',
      scope: ['profile'],
      lang: 'ru',
    })
    await complete(page, { id_token: 'telegram-signed-token' })
    await expect(page.getByRole('heading', { name: 'Выходим на поле.' })).toBeVisible()
    await expect(page.getByRole('button', { name: 'Новая игра' })).toHaveCount(0)
    await page.reload()
    await expect(page.getByRole('heading', { name: 'Выходим на поле.' })).toBeVisible()
    await expect(login).toHaveCount(0)
    expect(page.url()).toContain(`game=${gameId}`)
  })
}

test('a temporary profile failure preserves the browser session for reload', async ({ page }) => {
  const token = await configure(page)
  let failed = false
  await page.route('**/api/me', async (route) => {
    if (!failed) {
      failed = true
      await route.fulfill({ status: 503, json: { detail: 'Временная ошибка профиля' } })
    } else await route.continue()
  })
  await page.goto('/')
  await page.getByRole('button', { name: 'Войти через Telegram', exact: true }).click()
  await complete(page, { id_token: 'telegram-signed-token' })
  await expect(page.getByRole('alert')).toHaveText('Временная ошибка профиля')
  expect(await page.evaluate(() => sessionStorage.getItem('fczhk-session'))).toBe(token)
  await page.reload()
  await expect(page.getByRole('heading', { name: 'Выходим на поле.' })).toBeVisible()
})

test('browser login recovers after cancellation, membership denial and explicit retry', async ({
  page,
}) => {
  await configure(page)
  await page.goto('/')
  const login = page.getByRole('button', { name: 'Войти через Telegram', exact: true })
  await login.click()
  await complete(page, { error: 'popup_closed' })
  await expect(page.getByRole('alert')).toContainText('Вход отменён')
  await expect(login).toBeEnabled()
  await page.route('**/api/auth/telegram/browser', async (route) => {
    await route.fulfill({
      status: 403,
      json: { detail: 'Доступ только для участников нашего чата или канала' },
    })
  })
  await login.click()
  await complete(page, { id_token: 'telegram-signed-token' })
  await expect(page.getByRole('alert')).toContainText('Доступ только для участников')
  await expect(login).toBeEnabled()
  await login.click()
  await page.getByRole('button', { name: 'Отменить вход', exact: true }).click()
  await expect(login).toBeEnabled()
  expect(await page.evaluate(() => (window as LoginWindow).completeLogin)).toBeNull()
})

test('SDK download failure can be retried', async ({ page }) => {
  await configure(page)
  let unavailable = true
  await page.route('https://telegram.org/js/telegram-login.js', async (route) => {
    if (unavailable) await route.abort()
    else await route.fulfill({ contentType: 'application/javascript', body: sdk })
  })
  await page.goto('/')
  await expect(page.getByRole('alert')).toContainText('Не удалось загрузить вход через Telegram')
  unavailable = false
  await page.getByRole('button', { name: 'Повторить подключение' }).click()
  await expect(
    page.getByRole('button', { name: 'Войти через Telegram', exact: true }),
  ).toBeEnabled()
})

test('unconfigured browser login keeps the bot link available', async ({ page }) => {
  await configure(page)
  await page.route('**/api/auth/options', async (route) => {
    await route.fulfill({
      json: { browser_login: false, bot_url: 'https://t.me/football_test_bot' },
    })
  })
  await page.goto('/')
  await expect(page.getByRole('link', { name: 'Открыть Telegram-бота' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Войти через Telegram', exact: true })).toHaveCount(
    0,
  )
})
