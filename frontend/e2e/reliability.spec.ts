import { expect, test } from '@playwright/test'

test('valid session survives stale Mini App initData and logout revokes it', async ({ page }) => {
  const login = await page.request.post('/api/auth/demo/player')
  const { token } = await login.json()
  await page.addInitScript(
    ({ token }) => {
      sessionStorage.setItem('fczhk-session', token)
      window.Telegram = { WebApp: { initData: 'expired-data', ready() {}, expand() {} } }
    },
    { token },
  )
  let attempts = 0
  await page.route('**/api/auth/telegram', (route) => {
    attempts++
    return route.fulfill({ status: 401, json: { detail: 'initData expired' } })
  })
  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'Выходим на поле.' })).toBeVisible()
  expect(attempts).toBe(0)
  await page.reload()
  await expect(page.getByRole('heading', { name: 'Выходим на поле.' })).toBeVisible()
  expect(attempts).toBe(0)
  await page.getByRole('button', { name: 'Профиль', exact: true }).click()
  await page.getByRole('button', { name: 'Выйти из аккаунта' }).click()
  await expect(page.getByRole('button', { name: 'Войти игроком', exact: true })).toBeVisible()
  const revoked = await page.request.get('/api/me', {
    headers: { Authorization: `Bearer ${token}` },
  })
  expect(revoked.status()).toBe(401)
})

test('expired session returns to login and admin can cancel a future game', async ({
  page,
}, testInfo) => {
  await page.goto('/')
  await page.getByRole('button', { name: 'Войти администратором' }).click()
  await expect(page.getByRole('heading', { name: 'Выходим на поле.' })).toBeVisible()
  const token = await page.evaluate(() => sessionStorage.getItem('fczhk-session'))
  const headers = { Authorization: `Bearer ${token}` }
  const created = await page.request.post('/api/matches', {
    headers,
    data: {
      starts_at: new Date(Date.UTC(2049, 5, 4 + testInfo.repeatEachIndex, 17)).toISOString(),
      location: 'Отменяемая игра',
    },
  })
  expect(created.status()).toBe(201)
  const match = await created.json()
  await page.request.post(`/api/matches/${match.id}/actions/open`, {
    headers,
    data: { version: match.version },
  })
  await page.goto(`/?game=${match.id}`)
  await page.getByRole('tab', { name: 'Обзор', exact: true }).click()
  await page.getByRole('button', { name: 'Отменить игру', exact: true }).click()
  await page.getByRole('radio', { name: 'Да, перенести', exact: true }).check()
  await page.getByLabel('Причина отмены').fill('Поле закрыто')
  await page
    .getByRole('dialog')
    .getByRole('button', { name: 'Подтвердить отмену игры', exact: true })
    .click()
  await expect(page.locator('.archived-game')).toContainText('Игра отменена')
  await expect(page.getByRole('button', { name: 'Записаться полевым' })).toHaveCount(0)
  await page.getByRole('button', { name: 'Настройки', exact: true }).click()
  await page.getByRole('tab', { name: 'Диагностика', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Доставка сообщений' })).toBeVisible()
  await page.getByRole('button', { name: 'Игра', exact: true }).click()
  await expect(page.locator('.match-hero')).toBeVisible()
  // Revoke when the explicit refresh reaches the server. A background poll must
  // not log out the app before Playwright can click the authenticated controls.
  await page.route(
    '**/api/matches/current',
    async (route) => {
      const revoked = await page.request.post('/api/auth/logout', { headers })
      expect(revoked.ok()).toBe(true)
      await route.continue()
    },
    { times: 1 },
  )
  const expired = page.waitForResponse(
    (response) =>
      new URL(response.url()).pathname === '/api/matches/current' && response.status() === 401,
  )
  await page.getByRole('button', { name: 'Обновить игру' }).click()
  await expired
  await expect(page.getByRole('button', { name: 'Войти администратором' })).toBeVisible()
})

test('navigation during login survives a slower game response', async ({ page }) => {
  let releaseGame!: () => void
  const waiting = new Promise<void>((resolve) => {
    releaseGame = resolve
  })
  await page.route(
    '**/api/matches/current',
    async (route) => {
      await waiting
      await route.continue()
    },
    { times: 1 },
  )
  const gameResponse = page.waitForResponse(
    (response) => new URL(response.url()).pathname === '/api/matches/current',
  )
  try {
    await page.goto('/')
    await page.getByRole('button', { name: 'Войти администратором' }).click()
    const settings = page.getByRole('button', { name: 'Настройки', exact: true })
    await expect(settings).toBeDisabled()
    await page.getByRole('button', { name: 'Игроки', exact: true }).click()
    releaseGame()
    await gameResponse
    // The login task has finished when its busy state is cleared.
    await expect(settings).toBeEnabled()
    await expect(page.getByRole('button', { name: 'Игроки', exact: true })).toHaveClass('active')
    await settings.click()
    await page.getByRole('tab', { name: 'Диагностика', exact: true }).click()
    await expect(page.getByRole('heading', { name: 'Доставка сообщений' })).toBeVisible()
    await expect(settings).toHaveClass('active')
  } finally {
    releaseGame()
  }
})

test('archive requests summaries only when opened and pages on demand', async ({ page }) => {
  const pages: string[] = []
  await page.route('**/api/matches?*', (route) => {
    pages.push(route.request().url())
    const offset = Number(new URL(route.request().url()).searchParams.get('offset') || 0)
    return route.fulfill({
      json: Array.from({ length: offset ? 1 : 20 }, (_, i) => ({
        id: offset + i + 900,
        starts_at: '2020-01-03T20:00:00+03:00',
        game_day: '2020-01-03',
        location: 'Архив',
        historical: true,
        status: 'completed',
        version: 1,
        participant_count: 18,
        result: { completed: true, score: { white: 2, black: 1 } },
      })),
    })
  })
  await page.goto('/')
  await page.getByRole('button', { name: 'Войти игроком', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Выходим на поле.' })).toBeVisible()
  expect(pages).toHaveLength(0)
  await page.getByRole('button', { name: 'Архив', exact: true }).click()
  await expect(page.locator('.archive-card')).toHaveCount(20)
  await page.getByRole('button', { name: 'Показать ещё' }).click()
  await expect(page.locator('.archive-card')).toHaveCount(21)
  expect(pages.at(-1)).toContain('offset=20')
  await expect(page.getByRole('button', { name: 'Показать ещё' })).toHaveCount(0)
})

test('player requests historical profile and admin confirms it and skips a week', async ({
  page,
  request,
}) => {
  const admin = await (await request.post('/api/auth/demo/admin')).json()
  const headers = { Authorization: `Bearer ${admin.token}` }
  const guest = await (
    await request.post('/api/players/guests', { headers, data: { alias: 'История профиля E2E' } })
  ).json()
  await page.goto('/')
  await page.getByRole('button', { name: 'Войти игроком', exact: true }).click()
  await page.getByRole('button', { name: 'Профиль', exact: true }).click()
  await page.getByRole('tab', { name: 'Настройки', exact: true }).click()
  await page.getByLabel('Поиск исторической карточки').fill('История профиля E2E')
  await page.getByLabel('Моя прежняя карточка').selectOption(String(guest.id))
  await page.getByRole('button', { name: 'Запросить привязку' }).click()
  await expect(page.getByRole('status').filter({ hasText: 'Ожидает подтверждения' })).toBeVisible()
  await page.getByRole('button', { name: 'Выйти из аккаунта' }).click()
  await page.getByRole('button', { name: 'Войти администратором' }).click()
  await page.getByRole('button', { name: 'Настройки', exact: true }).click()
  await page.getByRole('tab', { name: 'Профили', exact: true }).click()
  page.on('dialog', (dialog) => dialog.accept())
  await page.getByRole('button', { name: 'Подтвердить связь' }).click()
  await expect(page.getByText('Нет заявок на подтверждение.')).toBeVisible()
  const players = await (await request.get('/api/players', { headers })).json()
  expect(players.some((p: { id: number }) => p.id === guest.id)).toBe(false)
  expect(
    players.some((p: { alias: string; guest: boolean }) => p.alias === guest.alias && !p.guest),
  ).toBe(true)
  await page.getByRole('tab', { name: 'Расписание', exact: true }).click()
  await page.getByText('Пропуски недель', { exact: true }).click()
  await page.getByLabel('Дата игры', { exact: true }).fill('2048-06-05')
  await page.getByLabel('Причина пропуска').fill('Тестовый перерыв')
  await page.getByRole('button', { name: 'Пропустить неделю', exact: true }).click()
  await expect(page.getByText(/5 июня · Тестовый перерыв/)).toBeVisible()
  await page.getByRole('button', { name: 'Вернуть в расписание' }).click()
  await expect(page.getByText(/5 июня · Тестовый перерыв/)).toHaveCount(0)
  await page.screenshot({ path: 'test-results/operations-mobile.png', fullPage: true })
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  await page.getByRole('button', { name: 'Профиль', exact: true }).click()
  await page.getByRole('button', { name: 'Выйти из аккаунта' }).click()
  await page.getByRole('button', { name: 'Войти игроком', exact: true }).click()
  await page.getByRole('button', { name: 'Профиль', exact: true }).click()
  await page.getByRole('tab', { name: 'Настройки', exact: true }).click()
  await expect(page.getByLabel('Игровой alias')).toHaveValue(guest.alias)
  await expect(
    page.getByRole('status').filter({ hasText: `Карточка привязана: ${guest.alias}` }),
  ).toBeVisible()
})
