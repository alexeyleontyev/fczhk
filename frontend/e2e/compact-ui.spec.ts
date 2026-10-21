import { expect, test } from '@playwright/test'

test('one shared keeper card has no personal ratings or profile linking actions', async ({
  page,
  request,
}) => {
  const auth = await (await request.post('/api/auth/demo/admin')).json()
  const headers = { Authorization: `Bearer ${auth.token}` }
  const created = await request.post('/api/players/guests', {
    headers,
    data: { alias: 'Приглашённый вратарь' },
  })
  expect(created.status()).toBe(201)
  await page.addInitScript((token) => sessionStorage.setItem('fczhk-session', token), auth.token)
  await page.goto('/')
  await page.getByRole('button', { name: 'Игроки', exact: true }).click()
  await page.getByRole('searchbox', { name: 'Поиск игроков', exact: true }).fill('приглашенный')
  const card = page.locator('.catalog-person')
  await expect(card).toHaveCount(1)
  await expect(card.getByRole('heading')).toContainText('Приглашённый вратарь')
  await card.locator('summary').click()
  await expect(card).toContainText('Для игр с неизвестным или сменным вратарём.')
  await expect(card.getByRole('button')).toHaveCount(0)
  await page.getByRole('button', { name: 'Оценить игроков', exact: true }).click()
  await expect(
    page.getByLabel('Оцениваемый игрок').getByRole('option', {
      name: 'Приглашённый вратарь',
      exact: true,
    }),
  ).toHaveCount(0)
})

test('compact workspaces: one search, lazy ratings, circled metrics and details on demand', async ({
  page,
  request,
}) => {
  const auth = await (await request.post('/api/auth/demo/admin')).json()
  const headers = { Authorization: `Bearer ${auth.token}` }
  const alias = `Компактный игрок ${Date.now()}`
  const player = await (
    await request.post('/api/players/guests', { headers, data: { alias } })
  ).json()
  const vote = await request.put(`/api/players/${player.id}/ratings`, {
    headers,
    data: { position: 'field', attack: 1.2, defense: 3.4, revision: 0 },
  })
  expect(vote.ok()).toBe(true)
  await page.addInitScript((token) => sessionStorage.setItem('fczhk-session', token), auth.token)
  const requested: string[] = []
  page.on('request', (r) => requested.push(new URL(r.url()).pathname))
  await page.goto('/')
  await page.getByRole('button', { name: 'Игроки', exact: true }).click()
  const tabs = page.getByRole('tablist', { name: 'Разделы игроков', exact: true })
  await expect(tabs.getByRole('tab', { name: 'Каталог', exact: true })).toHaveAttribute(
    'aria-selected',
    'true',
  )
  expect(requested.includes('/api/leaderboards')).toBe(false)
  expect(requested.includes('/api/game-ratings')).toBe(false)
  const search = page.getByRole('searchbox', { name: 'Поиск игроков', exact: true })
  await expect(search).toHaveCount(1)
  await search.fill(alias)
  const row = page.locator('.catalog-person').filter({ hasText: alias })
  await expect(row.getByRole('heading', { name: alias, exact: true })).toBeVisible()
  await expect(row.locator('summary')).toContainText('4,6')
  await expect(row.getByRole('button', { name: 'Статистика', exact: true })).toBeHidden()
  await row.locator('summary').click()
  await row.getByRole('button', { name: 'Статистика', exact: true }).click()
  await expect(page.getByRole('dialog')).toContainText(`Статистика: ${alias}`)
  await page.keyboard.press('Escape')
  await tabs.getByRole('tab', { name: 'Рейтинги', exact: true }).click()
  await expect(search).toHaveValue(alias)
  await expect(page.locator('.leaderboard-list tbody tr')).toHaveCount(1)
  await expect(page.locator('.leaderboard-list th .rating-mark')).toHaveCount(2)
  await expect(page.locator('.leaderboard-list tbody')).toContainText('1,2')
  await expect(page.locator('.leaderboard-list tbody')).toContainText('3,4')
  await expect(page.locator('.leaderboard-list tbody')).toContainText('4,6')
  await page
    .getByRole('combobox', { name: 'Показатель зачёта', exact: true })
    .selectOption('field_defense')
  await expect(page.locator('.leaderboard-list th .rating-mark')).toHaveCount(1)
  await expect(page.locator('.leaderboard-list tbody tr td').last()).toHaveText('3,4')
  await expect(page.locator('.game-rating-board')).toHaveCount(0)
  await page.getByRole('tab', { name: 'OpenSkill', exact: true }).click()
  await expect(
    page.getByRole('heading', { name: 'Общий рейтинг OpenSkill', exact: true }),
  ).toBeVisible()
  await expect(page.locator('.leaderboard-board')).toHaveCount(0)
  await tabs.getByRole('tab', { name: 'Каталог', exact: true }).click()
  await tabs.getByRole('tab', { name: 'Каталог', exact: true }).focus()
  await page.keyboard.press('ArrowRight')
  await expect(tabs.getByRole('tab', { name: 'Зачёты', exact: true })).toHaveAttribute(
    'aria-selected',
    'true',
  )
  await page.keyboard.press('Home')
  await expect(tabs.getByRole('tab', { name: 'Каталог', exact: true })).toHaveAttribute(
    'aria-selected',
    'true',
  )
  await row.locator('summary').click()
  for (const width of [320, 390, 1440]) {
    await page.setViewportSize({ width, height: 900 })
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
    await page.screenshot({ path: `test-results/compact-catalog-${width}.png`, fullPage: true })
  }
  await page.getByRole('button', { name: 'Профиль', exact: true }).click()
  await page.getByRole('tab', { name: 'Настройки', exact: true }).click()
  await expect(page.getByLabel('Игровой alias')).toBeVisible()
  await expect(page.locator('.statistics')).toBeHidden()
  await page.getByRole('button', { name: 'Настройки', exact: true }).click()
  await page.getByRole('tab', { name: 'Администраторы', exact: true }).click()
  await expect(page.getByRole('region', { name: 'Администраторы', exact: true })).toBeVisible()
  await expect(page.getByLabel('Время игры · Москва', { exact: true })).toHaveCount(0)
})
