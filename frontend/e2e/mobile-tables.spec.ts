import { expect, test } from '@playwright/test'

test('catalog saves field and keeper votes inline and rejects a stale revision', async ({
  page,
  request,
}) => {
  const auth = await (await request.post('/api/auth/demo/admin')).json()
  const headers = { Authorization: `Bearer ${auth.token}` }
  const alias = `Табличные оценки ${Date.now()}`
  const guest = await (
    await request.post('/api/players/guests', { headers, data: { alias } })
  ).json()
  const otherAlias = `${alias} другой`
  const other = await (
    await request.post('/api/players/guests', { headers, data: { alias: otherAlias } })
  ).json()
  await page.route('**/api/matches/last-completed', (route) =>
    route.fulfill({ json: { id: 99, participant_ids: [guest.id, other.id] } }),
  )
  await page.addInitScript((token) => sessionStorage.setItem('fczhk-session', token), auth.token)
  await page.goto('/')
  await page.getByRole('button', { name: 'Игроки', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Оценить игроков', exact: true })).toHaveCount(0)
  await page.getByLabel('Поиск игроков', { exact: true }).fill(alias)
  const row = page
    .locator('.catalog-person')
    .filter({ has: page.getByRole('button', { name: alias, exact: true }) })
  const attack = row.getByLabel(`Моя атака: ${alias}`, { exact: true })
  const defense = row.getByLabel(`Моя защита: ${alias}`, { exact: true })
  const save = row.getByRole('button', { name: `Сохранить оценки: ${alias}`, exact: true })
  await page.getByLabel('Только участники предыдущей игры', { exact: true }).check()
  await expect(page.locator('.catalog-person')).toHaveCount(2)
  const otherDraft = page.getByLabel(`Моя защита: ${otherAlias}`, { exact: true })
  await otherDraft.fill('2,7')
  await expect(save).toBeDisabled()
  await attack.fill('0')
  await defense.fill('4,2')
  await save.click()
  await expect(
    page.getByRole('status').filter({ hasText: `Оценки сохранены: ${alias}` }),
  ).toBeVisible()
  await expect(save).toBeDisabled()
  await expect(row.locator('.catalog-total')).toHaveText('4,2')
  await expect(otherDraft).toHaveValue('2,7')
  await expect(page.locator('.catalog-person')).toHaveCount(2)
  await defense.fill('4,5')
  expect(
    (
      await request.put(`/api/players/${guest.id}/ratings`, {
        headers,
        data: { position: 'field', attack: 1, defense: 2, revision: 1 },
      })
    ).ok(),
  ).toBe(true)
  await save.click()
  await expect(
    page.getByRole('alert').filter({ hasText: 'Ваша оценка уже изменена' }),
  ).toBeVisible()
  await expect(defense).toHaveValue('4,5')
  await attack.fill('2')
  await expect(save).toBeDisabled()
  await page.getByRole('button', { name: 'Загрузить актуальные оценки', exact: true }).click()
  await expect(attack).toHaveValue('1')
  await expect(defense).toHaveValue('2')
  await defense.fill('3,3')
  await save.click()
  await expect(save).toBeDisabled()
  expect(
    (await (await request.get(`/api/players/${guest.id}/ratings/field`, { headers })).json()).own
      .defense,
  ).toBe(3.3)
  await page
    .getByRole('tablist', { name: 'Амплуа для оценки' })
    .getByRole('tab', { name: 'Вратари', exact: true })
    .click()
  await expect(attack).toHaveCount(0)
  await defense.fill('0')
  await save.click()
  await expect(save).toBeDisabled()
  expect(
    (await (await request.get(`/api/players/${guest.id}/ratings/keeper`, { headers })).json()).own
      .defense,
  ).toBe(0)
  await page
    .getByRole('tablist', { name: 'Амплуа для оценки' })
    .getByRole('tab', { name: 'Полевые', exact: true })
    .click()
  await expect(attack).toHaveValue('1')
  await expect(defense).toHaveValue('3,3')
  await page.getByLabel('Только участники предыдущей игры', { exact: true }).uncheck()
  await page.getByLabel('Поиск игроков', { exact: true }).fill(auth.player.alias)
  await expect(page.locator('.catalog-person input')).toHaveCount(0)
})

test('previous-game filter, sorting every column and pinned games at mobile widths', async ({
  page,
  request,
}) => {
  const auth = await (await request.post('/api/auth/demo/player')).json()
  const headers = { Authorization: `Bearer ${auth.token}` }
  const people = await (await request.get('/api/players', { headers })).json()
  const selected = people.filter((p: { shared_keeper?: boolean }) => !p.shared_keeper).slice(0, 3)
  await page.route('**/api/matches/last-completed', (route) =>
    route.fulfill({ json: { id: 99, participant_ids: [selected[0].id, selected[1].id] } }),
  )
  const rows = selected.map((p: { id: number; alias: string }, i: number) => ({
    player_id: p.id,
    alias: p.alias,
    games: 20 - i * 4,
    wins: 8 + i,
    draws: i,
    losses: 12 - i * 6,
    points: 24 + i * 4,
    goals: 13 - i,
    assists: i * 3,
    goal_assist: 13 + i * 2,
    win_rate: 40 + i * 10,
  }))
  await page.route('**/api/leaderboards*', (route) =>
    route.fulfill({
      json: {
        results: { matches: 20, boards: { points: [...rows].reverse() } },
        community: { boards: {} },
      },
    }),
  )
  await page.addInitScript((token) => sessionStorage.setItem('fczhk-session', token), auth.token)
  await page.goto('/')
  await page.getByRole('button', { name: 'Игроки', exact: true }).click()
  await page.getByLabel('Только участники предыдущей игры', { exact: true }).check()
  await expect(page.locator('.catalog-person')).toHaveCount(2)
  for (const width of [320, 390, 1440]) {
    await page.setViewportSize({ width, height: 900 })
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
    const saveBounds = await page.locator('.catalog-save').first().boundingBox()
    expect(saveBounds!.x + saveBounds!.width).toBeLessThanOrEqual(width)
    await page.screenshot({ path: `test-results/table-catalog-${width}.png`, fullPage: true })
  }
  await page
    .getByRole('tablist', { name: 'Разделы игроков', exact: true })
    .getByRole('tab', { name: 'Зачёты', exact: true })
    .click()
  const table = page.locator('.results-table')
  await expect(table.locator('tbody tr')).toHaveCount(3)
  for (const label of [
    '№',
    'Игрок',
    'Игры',
    'Очки',
    'Победы',
    'Ничьи',
    'Поражения',
    'Голы',
    'Передачи',
    'Гол + пас',
    'Винрейт',
  ]) {
    const header = table
      .getByRole('columnheader')
      .filter({ has: page.getByRole('button', { name: label, exact: true }) })
    await header.getByRole('button').click()
    const first = await table.locator('tbody .result-name').allTextContents()
    await header.getByRole('button').click()
    expect(await table.locator('tbody .result-name').allTextContents()).toEqual(
      [...first].reverse(),
    )
  }
  for (const width of [320, 390, 1440]) {
    await page.setViewportSize({ width, height: 900 })
    const region = page.getByRole('region', {
      name: 'Зачёты с горизонтальной прокруткой',
      exact: true,
    })
    await region.evaluate((el) => {
      el.scrollLeft = 0
    })
    const nameBefore = await table.locator('tbody .result-name').first().boundingBox()
    const gamesBefore = await table.locator('tbody .result-games').first().boundingBox()
    await region.evaluate((el) => {
      el.scrollLeft = el.scrollWidth
    })
    const nameAfter = await table.locator('tbody .result-name').first().boundingBox()
    const gamesAfter = await table.locator('tbody .result-games').first().boundingBox()
    expect(Math.abs(nameBefore!.x - nameAfter!.x)).toBeLessThan(1)
    expect(Math.abs(gamesBefore!.x - gamesAfter!.x)).toBeLessThan(1)
    expect(nameAfter!.x + nameAfter!.width).toBeLessThanOrEqual(gamesAfter!.x + 1)
    expect(gamesAfter!.x + gamesAfter!.width).toBeLessThanOrEqual(width)
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
    await page.screenshot({
      path: `test-results/table-results-pinned-${width}.png`,
      fullPage: true,
    })
  }
})

for (const role of ['admin', 'player']) {
  test(`no collection: ${role} sees countdown and archive; admin has schedule shortcut`, async ({
    page,
    request,
  }) => {
    const auth = await (await request.post(`/api/auth/demo/${role}`)).json()
    const headers = { Authorization: `Bearer ${auth.token}` }
    const current = await (await request.get('/api/matches/current', { headers })).json()
    await page.route('**/api/matches/current', (route) =>
      route.fulfill({ json: { ...current, status: 'completed' } }),
    )
    await page.route('**/api/matches/last-completed', (route) =>
      route.fulfill({
        json: {
          ...current,
          participant_ids: [],
          result: { completed: true, score: { white: 6, black: 8 } },
        },
      }),
    )
    await page.route('**/api/schedule/next', (route) =>
      route.fulfill({
        json: {
          server_now: '2026-10-25T22:00:00+03:00',
          opening_at: '2026-10-27T12:00:00+03:00',
          starts_at: '2026-10-30T20:00:00+03:00',
          location: 'Манеж',
        },
      }),
    )
    await page.addInitScript((token) => sessionStorage.setItem('fczhk-session', token), auth.token)
    await page.goto('/')
    await expect(page.getByRole('heading', { name: 'Следующая игра', exact: true })).toBeVisible()
    await expect(page.getByRole('timer')).toContainText('1 д.')
    await expect(page.locator('.collection-countdown')).toContainText('12:00')
    await expect(page.locator('.previous-game-score')).toContainText('6 : 8')
    await expect(page.getByRole('button', { name: 'Игра', exact: true })).toHaveClass('active')
    if (role === 'admin') {
      await page.getByRole('button', { name: 'Настройки', exact: true }).click()
      await page.getByRole('tab', { name: 'Администраторы', exact: true }).click()
      await page.getByRole('button', { name: 'Игра', exact: true }).click()
      await page.getByRole('button', { name: /Управление → Расписание/ }).click()
      await expect(page.getByRole('tab', { name: 'Расписание', exact: true })).toHaveAttribute(
        'aria-selected',
        'true',
      )
      await expect(page.getByLabel('Время открытия сбора · Москва', { exact: true })).toBeVisible()
      await page.getByRole('button', { name: 'Игра', exact: true }).click()
    } else
      await expect(page.getByRole('button', { name: /Управление → Расписание/ })).toHaveCount(0)
    await page.getByRole('button', { name: 'Итог, голы и составы', exact: true }).click()
    await expect(page.getByRole('heading', { name: 'Выходим на поле.' })).toBeVisible()
    await page.getByRole('button', { name: 'Игра', exact: true }).click()
    await page.route('**/api/schedule/next', (route) =>
      route.fulfill({
        json: {
          server_now: '2026-10-25T22:00:00+03:00',
          opening_at: null,
          starts_at: null,
          location: null,
        },
      }),
    )
    await page.reload()
    await expect(
      page.getByRole('heading', { name: 'Следующий сбор ещё не запланирован', exact: true }),
    ).toBeVisible()
    await expect(page.getByRole('timer')).toHaveCount(0)
    await page.screenshot({ path: `test-results/next-game-${role}-390.png`, fullPage: true })
  })
}
