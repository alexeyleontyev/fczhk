import { expect, test, type Page } from '@playwright/test'

type TelegramTestWindow = Window & {
  pressTelegramBack: () => void
  telegramBackVisible: boolean
  telegramBackHandlers: number
}

async function pressBack(page: Page) {
  await page.evaluate(() => (window as TelegramTestWindow).pressTelegramBack())
}

test('Telegram back restores nested statistics, catalog search and current game; logout clears it', async ({
  page,
}) => {
  const { token } = await (await page.request.post('/api/auth/demo/player')).json()
  const headers = { Authorization: `Bearer ${token}` }
  const people = await (await page.request.get('/api/players', { headers })).json()
  const [person, partner] = people
  const stats = await (
    await page.request.get(`/api/players/${person.id}/stats`, { headers })
  ).json()
  const current = await (await page.request.get('/api/matches/current', { headers })).json()
  const detailId = 987600
  await page.route('https://telegram.org/js/telegram-web-app.js', (route) =>
    route.fulfill({ contentType: 'application/javascript', body: '' }),
  )
  await page.addInitScript(
    ({ token }) => {
      sessionStorage.setItem('fczhk-session', token)
      const state = window as TelegramTestWindow
      const callbacks = new Set<() => void>()
      state.telegramBackVisible = false
      state.telegramBackHandlers = 0
      state.pressTelegramBack = () => callbacks.forEach((callback) => callback())
      window.Telegram = {
        WebApp: {
          initData: 'test-session-already-authenticated',
          ready() {},
          expand() {},
          isVersionAtLeast: () => true,
          BackButton: {
            show() {
              state.telegramBackVisible = true
            },
            hide() {
              state.telegramBackVisible = false
            },
            onClick(callback) {
              callbacks.add(callback)
              state.telegramBackHandlers = callbacks.size
            },
            offClick(callback) {
              callbacks.delete(callback)
              state.telegramBackHandlers = callbacks.size
            },
          },
        },
      }
    },
    { token },
  )
  await page.route(`**/api/matches/${detailId}`, (route) =>
    route.fulfill({
      json: { ...current, id: detailId, location: 'Игра из статистики' },
    }),
  )
  await page.route(`**/api/players/${person.id}/stats*`, (route) =>
    route.fulfill({
      json: {
        ...stats,
        matches: [
          {
            match_id: detailId,
            starts_at: current.starts_at,
            team: 'white',
            position: 'field',
            score: { white: 1, black: 0 },
            goals: 1,
            assists: 0,
          },
        ],
        partners: [
          {
            player_id: partner.id,
            alias: partner.alias,
            games: 1,
            wins: 1,
            draws: 0,
            losses: 0,
            win_rate: 100,
          },
        ],
      },
    }),
  )
  await page.goto(`/?game=${current.id}&screen=auction`)
  await expect(page.getByRole('heading', { name: 'Аукцион капитанов', exact: true })).toBeVisible()
  expect(await page.evaluate(() => (window as TelegramTestWindow).telegramBackVisible)).toBe(true)
  await pressBack(page)
  await expect(page.getByRole('heading', { name: 'Выходим на поле.' })).toBeVisible()
  expect(await page.evaluate(() => (window as TelegramTestWindow).telegramBackVisible)).toBe(false)
  expect(await page.evaluate(() => (window as TelegramTestWindow).telegramBackHandlers)).toBe(1)
  await page.getByRole('button', { name: 'Игроки', exact: true }).click()
  await page.getByLabel('Поиск игроков', { exact: true }).fill(person.alias)
  await page.locator('.catalog-person summary').first().click()
  const open = page.locator('.player-card').getByRole('button', { name: 'Статистика', exact: true })
  await open.scrollIntoViewIfNeeded()
  const catalogScroll = await page.evaluate(() => window.scrollY)
  await open.click()
  await expect(
    page.getByRole('heading', { name: `Статистика: ${person.alias}`, exact: true }),
  ).toBeVisible()
  await page.getByRole('tab', { name: 'Партнёры', exact: true }).click()
  await page
    .getByRole('dialog')
    .getByRole('button', { name: new RegExp(partner.alias) })
    .click()
  await expect(
    page.getByRole('heading', { name: `Статистика: ${partner.alias}`, exact: true }),
  ).toBeVisible()
  await pressBack(page)
  await expect(
    page.getByRole('heading', { name: `Статистика: ${person.alias}`, exact: true }),
  ).toBeVisible()
  await page.getByRole('tab', { name: 'Матчи', exact: true }).click()
  await page.getByRole('dialog').locator('.stat-link').filter({ hasText: '1 : 0' }).click()
  await expect(page.locator('.match-hero')).toContainText('Игра из статистики')
  await pressBack(page)
  await expect(page.getByRole('dialog')).toBeVisible()
  await pressBack(page)
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await expect(page.getByLabel('Поиск игроков', { exact: true })).toHaveValue(person.alias)
  await expect.poll(() => page.evaluate(() => window.scrollY)).toBeCloseTo(catalogScroll, 0)
  await pressBack(page)
  await expect(page.locator('.match-hero')).toContainText(current.location)
  expect(await page.evaluate(() => (window as TelegramTestWindow).telegramBackVisible)).toBe(false)
  await page.getByRole('button', { name: 'Профиль', exact: true }).click()
  await page.getByRole('button', { name: 'Выйти из аккаунта' }).click()
  await expect(page.getByRole('button', { name: 'Войти игроком', exact: true })).toBeVisible()
  expect(await page.evaluate(() => (window as TelegramTestWindow).telegramBackVisible)).toBe(false)
  await page.getByRole('button', { name: 'Войти игроком', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Выходим на поле.' })).toBeVisible()
  expect(await page.evaluate(() => (window as TelegramTestWindow).telegramBackVisible)).toBe(false)
})

test('browser back button preserves archive pagination and closes nested guest form first', async ({
  page,
}) => {
  await page.route('**/api/matches?*', (route) => {
    const offset = Number(new URL(route.request().url()).searchParams.get('offset') || 0)
    return route.fulfill({
      json: Array.from({ length: offset ? 1 : 20 }, (_, i) => ({
        id: 988000 + offset + i,
        starts_at: '2020-01-03T20:00:00+03:00',
        game_day: '2020-01-03',
        location: 'Архив навигации',
        historical: true,
        status: 'completed',
        version: 1,
        participant_count: 18,
        result: { completed: true, score: { white: 2, black: 1 } },
      })),
    })
  })
  await page.goto('/')
  await page.getByRole('button', { name: 'Войти администратором' }).click()
  await expect(page.getByRole('heading', { name: 'Выходим на поле.' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Назад', exact: true })).toHaveCount(0)
  const token = await page.evaluate(() => sessionStorage.getItem('fczhk-session'))
  const current = await (
    await page.request.get('/api/matches/current', {
      headers: { Authorization: `Bearer ${token}` },
    })
  ).json()
  await page.route('**/api/matches/988020', (route) =>
    route.fulfill({ json: { ...current, id: 988020, location: 'Архив навигации' } }),
  )
  await page.getByRole('button', { name: 'Архив', exact: true }).click()
  await page.getByRole('button', { name: 'Показать ещё', exact: true }).click()
  await expect(page.locator('.archive-card')).toHaveCount(21)
  await page.locator('.archive-card').last().click()
  await expect(page.locator('.match-hero')).toContainText('Архив навигации')
  await page.getByRole('button', { name: 'Назад', exact: true }).click()
  await expect(page.locator('.archive-card')).toHaveCount(21)
  await page.getByRole('button', { name: 'Назад', exact: true }).click()
  await expect(page.locator('.match-hero')).toContainText(current.location)
  await expect(page.getByRole('button', { name: 'Назад', exact: true })).toHaveCount(0)
  await page.getByRole('tab', { name: 'Обзор', exact: true }).click()
  await page.getByRole('button', { name: 'Добавить игрока', exact: true }).click()
  await page.getByRole('button', { name: 'Создать нового гостя', exact: true }).click()
  await expect(page.getByRole('dialog', { name: 'Новый гость', exact: true })).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(page.getByRole('dialog', { name: 'Добавить в состав', exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Закрыть', exact: true }).click()
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Назад', exact: true })).toHaveCount(0)
  await page.getByRole('button', { name: 'Игроки', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Назад', exact: true })).toBeVisible()
  await page.screenshot({ path: 'test-results/back-navigation-mobile.png', fullPage: false })
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
})
