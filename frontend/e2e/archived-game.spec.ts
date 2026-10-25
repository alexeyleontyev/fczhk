import { expect, test } from '@playwright/test'

test('archived report shows frozen ratings, goals and metadata with private admin edits and history', async ({
  page,
  request,
}, testInfo) => {
  const auth = await (await request.post('/api/auth/demo/admin')).json()
  const headers = { Authorization: `Bearer ${auth.token}` }
  async function send(path: string, method = 'GET', data?: object) {
    const response = await request.fetch('/api' + path, { method, headers, data })
    expect(response.ok(), await response.text()).toBe(true)
    return response.json()
  }
  // Modern Moscow time is UTC+3. Early twentieth-century dates have historical
  // timezone offsets, so a random old year made the time assertion unreliable.
  const day = new Date(Date.UTC(2019, 1, 10 + testInfo.repeatEachIndex)).toISOString().slice(0, 10)
  let m = await send('/matches', 'POST', {
    starts_at: `${day}T20:30:00+03:00`,
    location: 'Манеж архива',
    season: '2026',
  })
  const white = await send('/players/guests', 'POST', { alias: `Белый архив ${m.id}` })
  const black = await send('/players/guests', 'POST', { alias: `Чёрный архив ${m.id}` })
  const keepers = []
  for (const side of ['Белые', 'Чёрные'])
    keepers.push(await send('/players/guests', 'POST', { alias: `Вратарь ${side} ${m.id}` }))
  const lineup = [
    { p: white, position: 'field', attack: 0, defense: 4, team: 'white' },
    { p: black, position: 'field', attack: 2, defense: 3, team: 'black' },
    { p: keepers[0], position: 'keeper', attack: null, defense: 4, team: 'white' },
    { p: keepers[1], position: 'keeper', attack: null, defense: 5, team: 'black' },
  ]
  for (const person of lineup) {
    m = await send(`/matches/${m.id}/participants`, 'POST', {
      version: m.version,
      player_id: person.p.id,
      position: person.position,
    })
    const reg = m.registrations.find((r: { player_id: number }) => r.player_id === person.p.id)
    m = await send(`/matches/${m.id}/registrations/${reg.id}/rating`, 'PUT', {
      version: m.version,
      position: person.position,
      attack: person.attack,
      defense: person.defense,
    })
  }
  for (const action of ['open', 'finalize'])
    m = await send(`/matches/${m.id}/actions/${action}`, 'POST', { version: m.version })
  const data = await send(`/matches/${m.id}/lineup`)
  m = await send(`/matches/${m.id}/lineup/confirm`, 'POST', {
    version: m.version,
    roster_version: m.roster_version,
    fingerprint: data.fingerprint,
    assignments: Object.fromEntries(
      m.registrations.map((r: { id: number; player_id: number }) => [
        r.id,
        lineup.find((p) => p.p.id === r.player_id)!.team,
      ]),
    ),
  })
  const event = (
    team: string,
    author_id: number | null,
    assist_id: number | null = null,
    kind = 'goal',
  ) => ({ id: crypto.randomUUID(), team, author_id, assist_id, kind })
  await send(`/matches/${m.id}/result`, 'PUT', {
    version: m.version,
    completed: true,
    participants: lineup.map((p) => ({ player_id: p.p.id, team: p.team, position: p.position })),
    goals: [
      event('white', white.id, keepers[0].id),
      event('white', null, null, 'own_goal'),
      event('black', black.id),
    ],
  })
  // Later community votes must not replace the scores saved for this game.
  await send(`/players/${black.id}/ratings`, 'PUT', {
    position: 'field',
    attack: 5,
    defense: 5,
    revision: 0,
  })
  await page.addInitScript((token) => {
    if (!sessionStorage.getItem('archive-test-session-initialized')) {
      sessionStorage.setItem('fczhk-session', token)
      sessionStorage.setItem('archive-test-session-initialized', '1')
    }
  }, auth.token)
  const requests: string[] = []
  page.on('request', (r) => requests.push(new URL(r.url()).pathname))
  await page.goto(`/?game=${m.id}`)
  const report = page.locator('.archived-game')
  await expect(report.getByLabel('Счёт матча', { exact: true })).toContainText('2 : 1')
  await expect(report.getByLabel('Сила сбора', { exact: true })).toContainText('Σ 18')
  await expect(report.getByLabel('Сила команды Белые', { exact: true })).toHaveText('Σ 8')
  await expect(report.getByLabel('Сила команды Чёрные', { exact: true })).toHaveText('Σ 10')
  await expect(report.locator('.archive-game-meta')).toContainText('20:30 МСК')
  await expect(report.locator('.archive-game-meta')).toContainText('Манеж архива')
  const blackRow = report
    .getByRole('table', { name: 'Оценки игроков: Чёрные' })
    .getByRole('row')
    .filter({ hasText: black.alias })
  await expect(blackRow.getByRole('cell')).toHaveText([black.alias, '2', '3', '5'])
  const whiteRow = report
    .getByRole('table', { name: 'Оценки игроков: Белые' })
    .getByRole('row')
    .filter({ hasText: white.alias })
  await expect(whiteRow.getByRole('cell')).toHaveText([white.alias, '0', '4', '4'])
  await expect(report.locator('thead .rating-mark')).toHaveCount(4)
  await expect(report.locator('.archive-goals')).toContainText([white.alias, black.alias])
  await expect(report.getByText('Автогол', { exact: true })).toBeVisible()
  expect(requests.some((path) => path.includes('/predictions') || path.includes('/auction'))).toBe(
    false,
  )
  for (const text of ['Выходим на поле.', 'Сбор на игру', 'Информация и оплата', 'Прогноз на игру'])
    await expect(report.getByText(text, { exact: true })).toHaveCount(0)
  for (const width of [320, 390, 1440]) {
    await page.setViewportSize({ width, height: 950 })
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
    await page.screenshot({ path: `test-results/archived-game-${width}.png`, fullPage: true })
  }
  await report.getByRole('button', { name: 'Изменить игру', exact: true }).click()
  await report.getByLabel('Время игры · Москва', { exact: true }).fill('21:15')
  await report.getByLabel('Место игры', { exact: true }).fill('Уточнённый манеж')
  await report.getByRole('button', { name: 'Сохранить параметры', exact: true }).click()
  await expect(report.locator('.archive-game-meta')).toContainText('21:15 МСК')
  await expect(report.locator('.archive-game-meta')).toContainText('Уточнённый манеж')
  await report.getByRole('button', { name: 'История изменений', exact: true }).click()
  const history = report.getByRole('region', { name: 'История изменений', exact: true })
  await expect(history).toContainText('Время: 20:30 → 21:15')
  await expect(history).toContainText('Место: Манеж архива → Уточнённый манеж')
  await expect(history).toContainText('Алексей')
  await history.getByText('Подробности изменений', { exact: true }).first().click()
  await expect(history).toContainText(new RegExp(`Добавлен гол \\d+: Белые · ${white.alias}`))
  await report.getByRole('button', { name: 'На поле', exact: true }).click()
  await expect(page.locator('.tactics-token')).toHaveCount(4)
  await expect(page.locator('.tactics-roster')).toHaveCount(0)
  await page.getByRole('tab', { name: 'Итог', exact: true }).click()
  await expect(report.getByLabel('Счёт матча', { exact: true })).toContainText('2 : 1')
  const imported = await send(`/matches/${m.id}`)
  await page.getByRole('button', { name: 'Сменить роль', exact: true }).click()
  await page.getByRole('button', { name: 'Войти игроком', exact: true }).click()
  await expect(report.locator('.archive-game-actions')).toHaveCount(0)
  await expect(report.getByLabel('Сила сбора', { exact: true })).toContainText('Σ 18')
  await expect(report.getByLabel('Счёт матча', { exact: true })).toContainText('2 : 1')
  await page.route(`**/api/matches/${m.id}`, (route) =>
    route.fulfill({
      json: {
        ...imported,
        historical: true,
        time_known: false,
        location: 'Не указано в историческом источнике',
      },
    }),
  )
  await page.reload()
  await expect(report.locator('.archive-game-meta')).toContainText('Время не указано')
  await expect(report.locator('.archive-game-meta')).toContainText('Место не указано')
  await page.getByRole('button', { name: 'Игра', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Выходим на поле.' })).toBeVisible()
  await expect(report).toHaveCount(0)
})
