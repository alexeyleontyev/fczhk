import { test, expect } from '@playwright/test'

test('transferred guests remain clickable; compact controls fit and team colors can be swapped on both views', async ({
  page,
  request,
}) => {
  const { token } = await (await request.post('/api/auth/demo/player')).json()
  const headers = { Authorization: `Bearer ${token}` }
  const games = await (await request.get('/api/matches?limit=1', { headers })).json()
  const m = await (await request.get(`/api/matches/${games[0].id}`, { headers })).json()
  const me = await (await request.get('/api/me', { headers })).json()
  const players = [
    {
      registration_id: 901,
      player_id: 901,
      alias: 'Гость',
      position: 'field',
      attack: 5,
      defense: 1,
    },
    {
      registration_id: 902,
      player_id: 902,
      alias: 'Белый полевой',
      position: 'field',
      attack: 1,
      defense: 5,
    },
    {
      registration_id: 903,
      player_id: 903,
      alias: 'Белый вратарь',
      position: 'keeper',
      attack: null,
      defense: 4,
    },
    {
      registration_id: 904,
      player_id: 904,
      alias: 'Чёрный полевой',
      position: 'field',
      attack: 1,
      defense: 5,
    },
    {
      registration_id: 905,
      player_id: 905,
      alias: 'Чёрный вратарь',
      position: 'keeper',
      attack: null,
      defense: 4,
    },
  ].map((p) => ({ ...p, community_attack: p.attack, community_defense: p.defense, game_mu: 25 }))
  const assignments = { 901: 'black', 902: 'white', 903: 'white', 904: 'black', 905: 'black' }
  const placements = {
    901: { x: 0.5, y: 0.44 },
    902: { x: 0.5, y: 0.56 },
    903: { x: 0.5, y: 0.935 },
    904: { x: 0.5, y: 0.2 },
    905: { x: 0.5, y: 0.065 },
  }
  const lineup = {
    version: m.version,
    roster_version: m.roster_version,
    fingerprint: 'a'.repeat(64),
    players,
    official_players: players,
    assignments,
    official_assignments: assignments,
    placements,
    editable: true,
    min_field_players: 2,
    require_two_keepers: false,
    auction: null,
    share_available: false,
  }
  await page.addInitScript((token) => sessionStorage.setItem('fczhk-session', token), token)
  await page.route(`**/api/matches/${m.id}`, (route) =>
    route.fulfill({
      json: {
        ...m,
        historical: false,
        status: 'approved',
        team_ratings: { summary: null, frozen: true, stale: false, method: 'manual' },
        result: {
          exists: false,
          completed: false,
          participants: [],
          goals: [],
          assist_team_switches: [],
        },
      },
    }),
  )
  await page.route(`**/api/matches/${m.id}/lineup`, (route) => route.fulfill({ json: lineup }))
  await page.route(`**/api/matches/${m.id}/lineup/proposals`, (route) =>
    route.fulfill({
      json: {
        mine_revision: 1,
        editable: true,
        proposals: [
          {
            id: 1,
            author_id: me.id,
            author: me.alias,
            revision: 1,
            roster_version: m.roster_version,
            fingerprint: lineup.fingerprint,
            updated_at: '2026-11-06T10:00:00Z',
            roster_stale: false,
            ratings_changed: false,
            players,
            assignments,
            placements,
          },
        ],
      },
    }),
  )
  await page.goto(`/?game=${m.id}&screen=lineup`)
  await page.getByLabel('Вариант состава').selectOption('draft')
  await page.getByRole('button', { name: 'Гость: перевести в белые', exact: true }).click()
  await expect(
    page
      .getByLabel('Белая команда', { exact: true })
      .getByRole('button', { name: 'Гость', exact: true }),
  ).toBeVisible()
  const swap = page.getByRole('button', { name: 'Поменять цвета команд', exact: true })
  await expect(swap).toBeVisible()
  await expect(
    page.getByRole('button', { name: 'Обновить предложение', exact: true }),
  ).toBeVisible()
  for (const width of [320, 360, 390, 768, 1440]) {
    await page.setViewportSize({ width, height: 1000 })
    const panel = await page.locator('.lineup-variant-picker').boundingBox()
    for (const button of await page.locator('.lineup-variant-picker button').all()) {
      const bounds = await button.boundingBox()
      expect(bounds && panel).toBeTruthy()
      expect(bounds!.x).toBeGreaterThanOrEqual(panel!.x)
      expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(panel!.x + panel!.width)
      expect(await button.evaluate((el) => el.scrollWidth <= el.clientWidth)).toBe(true)
    }
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  }
  await page.setViewportSize({ width: 320, height: 844 })
  await page.screenshot({ path: 'test-results/lineup-controls-320.png', fullPage: true })
  await page.getByRole('tab', { name: 'Поле', exact: true }).click()
  const guest = page.getByRole('button', { name: 'На поле: Гость', exact: true })
  const tokenCard = page.locator('.tactics-token').filter({ has: guest })
  await expect(tokenCard).toHaveClass(/white/)
  for (const width of [320, 390, 768, 1440]) {
    await page.setViewportSize({ width, height: 1000 })
    await guest.scrollIntoViewIfNeeded()
    // A visible element can still be fully covered by another token.
    await guest.click({ trial: true })
    expect((await tokenCard.boundingBox())!.width).toBeLessThanOrEqual(width <= 700 ? 80 : 104)
  }
  await page.setViewportSize({ width: 390, height: 844 })
  await page.screenshot({ path: 'test-results/lineup-guest-transfer-390.png', fullPage: true })
  await swap.click()
  await expect(tokenCard).toHaveClass(/black/)
  await guest.click({ trial: true })
  await page.getByRole('tab', { name: 'Команды', exact: true }).click()
  await expect(swap).toBeVisible()
  await swap.click()
  await expect(
    page
      .getByLabel('Белая команда', { exact: true })
      .getByRole('button', { name: 'Гость', exact: true }),
  ).toBeVisible()
  await page.reload()
  await page.getByLabel('Вариант состава').selectOption('draft')
  await page.getByRole('tab', { name: 'Поле', exact: true }).click()
  await expect(tokenCard).toHaveClass(/white/)
  await guest.click({ trial: true })
  // A formula change invalidates the saved draft, but refreshing its scores
  // must preserve the user's teams and valid manual positions.
  const stored = await page.evaluate(() => {
    const key = Object.keys(localStorage).find((k) => k.startsWith('fczhk-lineup-v1:'))!
    const draft = JSON.parse(localStorage.getItem(key)!)
    draft.fingerprint = 'b'.repeat(64)
    draft.placements['901'] = { x: 0.8, y: 0.74 }
    localStorage.setItem(key, JSON.stringify(draft))
    return { key, assignments: draft.assignments, placements: draft.placements }
  })
  await page.reload()
  await page.getByLabel('Вариант состава').selectOption('draft')
  await expect(page.getByRole('button', { name: 'Обновить прикидку', exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Обновить прикидку', exact: true }).click()
  const refreshed = await page.evaluate((key) => JSON.parse(localStorage.getItem(key)!), stored.key)
  expect(refreshed.assignments).toEqual(stored.assignments)
  expect(refreshed.placements).toEqual(stored.placements)
  await expect(tokenCard).toHaveClass(/white/)
  await guest.click({ trial: true })
  expect((await (await request.get(`/api/matches/${m.id}`, { headers })).json()).version).toBe(
    m.version,
  )
})
