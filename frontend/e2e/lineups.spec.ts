import { test, expect } from '@playwright/test'

test('completed lineup shows missing ratings as dashes and keeps genuine zero scores', async ({
  page,
  request,
}) => {
  const { token } = await (await request.post('/api/auth/demo/player')).json()
  const headers = { Authorization: `Bearer ${token}` }
  const games = await (await request.get('/api/matches?limit=1', { headers })).json()
  const m = await (await request.get(`/api/matches/${games[0].id}`, { headers })).json()
  const players = [
    {
      registration_id: -801,
      player_id: 81,
      alias: 'Исторический полевой',
      position: 'field',
      attack: null as number | null,
      defense: null as number | null,
      game_mu: null,
      source: 'missing',
    },
    {
      registration_id: -802,
      player_id: 82,
      alias: 'Исторический вратарь',
      position: 'keeper',
      attack: null as number | null,
      defense: null as number | null,
      game_mu: null,
      source: 'missing',
    },
  ]
  const assignments: Record<string, 'white' | 'black'> = { '-801': 'white', '-802': 'black' }
  await page.addInitScript((token) => sessionStorage.setItem('fczhk-session', token), token)
  await page.route(`**/api/matches/${m.id}`, (route) =>
    route.fulfill({
      json: {
        ...m,
        historical: true,
        status: 'completed',
        registrations: [],
        team_ratings: { summary: null, frozen: true, stale: false, method: 'legacy-manual' },
        result: {
          exists: true,
          completed: true,
          version: m.version,
          score: { white: 0, black: 0 },
          participants: players.map((p) => ({ ...p, team: assignments[p.registration_id] })),
          goals: [],
          assist_team_switches: [],
        },
      },
    }),
  )
  await page.route(`**/api/matches/${m.id}/lineup`, (route) =>
    route.fulfill({
      json: {
        version: m.version,
        roster_version: m.roster_version,
        fingerprint: 'historical-lineup',
        players,
        official_players: players,
        assignments,
        placements: {},
        editable: false,
        min_field_players: 2,
        require_two_keepers: false,
        auction: null,
      },
    }),
  )
  await page.goto(`/?game=${m.id}&screen=lineup`)
  await expect(page.getByRole('button', { name: 'На поле: Исторический полевой' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'На поле: Исторический вратарь' })).toBeVisible()
  const scores = page.getByLabel('Баллы команд')
  await expect(scores.locator(':scope > div > span')).toHaveText([
    'А —',
    'З —',
    'Σ —',
    'А —',
    'З —',
    'Σ —',
  ])
  await expect(scores).not.toContainText('≥')
  await expect(page.getByRole('button', { name: 'Утвердить состав' })).toHaveCount(0)
  await expect(page.locator('.tactics-roster')).toHaveCount(0)
  await page.screenshot({ path: 'test-results/historical-lineup-mobile.png', fullPage: true })
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)

  players[0].attack = players[0].defense = 0
  players[0].source = 'community'
  await page.reload()
  const white = scores.locator(':scope > div').first()
  await expect(white).toContainText('Σ 0')
  await expect(white).not.toContainText('≥')
  await expect(white).not.toContainText('—')
  await expect(page.locator('.tactics-screen')).not.toContainText(
    /Текущие оценки|Оценки сообщества/i,
  )

  players.push({
    ...players[0],
    registration_id: -803,
    player_id: 83,
    alias: 'Без оценки',
    attack: null,
    defense: null,
    source: 'missing',
  })
  assignments[-803] = 'white'
  await page.reload()
  await expect(white).toContainText('Σ ≥ 0')
})

test('tactical positions follow ratings; member drag/tap drafts are private, persistent and isolated', async ({
  page,
  browser,
  request,
}) => {
  const auth = await (await request.post('/api/auth/demo/admin')).json()
  const headers = { Authorization: `Bearer ${auth.token}` }
  async function send(path: string, method = 'GET', data?: object) {
    const r = await request.fetch('/api' + path, { method, headers, data })
    expect(r.ok(), await r.text()).toBe(true)
    return r.json()
  }
  const stamp = Date.now()
  const day = new Date(Date.UTC(2098, 0, 1) + Math.floor(Math.random() * 250) * 86400000)
    .toISOString()
    .slice(0, 10)
  let m = await send('/matches', 'POST', {
    starts_at: `${day}T20:00:00+03:00`,
    location: 'Проверка тактики',
  })
  const names: Record<string, string> = {}
  for (const color of ['white', 'black'])
    for (const role of [
      'forward',
      'defender',
      'defender2',
      'defender3',
      'equal',
      'equal2',
      'equal3',
      'substitute',
      'keeper',
    ]) {
      const alias = `${color} ${role} ${stamp}`
      names[`${color}_${role}`] = alias
      const p = await send('/players/guests', 'POST', { alias })
      const position = role === 'keeper' ? 'keeper' : 'field'
      m = await send(`/matches/${m.id}/participants`, 'POST', {
        version: m.version,
        player_id: p.id,
        position,
      })
      const reg = m.registrations.find((r: { player_id: number }) => r.player_id === p.id)
      m = await send(`/matches/${m.id}/registrations/${reg.id}/rating`, 'PUT', {
        version: m.version,
        position,
        attack:
          role === 'keeper'
            ? null
            : role === 'substitute'
              ? 0
              : role === 'forward'
                ? 5
                : role.startsWith('defender')
                  ? 1
                  : 3,
        defense:
          role === 'substitute'
            ? 0
            : role === 'forward'
              ? 1
              : role.startsWith('defender') || role === 'keeper'
                ? 5
                : 3,
      })
    }
  for (const action of ['open', 'finalize'])
    m = await send(`/matches/${m.id}/actions/${action}`, 'POST', { version: m.version })
  m = await send(`/matches/${m.id}/teams`, 'PUT', {
    version: m.version,
    assignments: Object.fromEntries(
      m.registrations.map((r: { id: number; alias: string }) => [
        r.id,
        r.alias.startsWith('white') ? 'white' : 'black',
      ]),
    ),
  })
  await page.setViewportSize({ width: 1440, height: 1600 })
  await page.goto(`/?game=${m.id}&screen=lineup`)
  await page.getByRole('button', { name: 'Войти игроком', exact: true }).click()
  await expect(page.locator('.tactics-token')).toHaveCount(18)
  await expect(page.getByRole('button', { name: 'Утвердить состав', exact: true })).toHaveCount(0)
  const token = (name: string) =>
    page.locator('.tactics-token').filter({
      has: page.getByRole('button', { name: `На поле: ${name}`, exact: true }),
    })
  const y = async (name: string) =>
    token(name).evaluate((el) => parseFloat((el as HTMLElement).style.top))
  for (const color of ['white', 'black']) {
    const [keeper, defender, equal, forward] = await Promise.all(
      ['keeper', 'defender', 'equal', 'forward'].map((role) => y(names[`${color}_${role}`])),
    )
    if (color === 'black') {
      expect(keeper).toBeLessThan(defender)
      expect(defender).toBeLessThan(equal)
      expect(equal).toBeLessThan(forward)
    } else {
      expect(keeper).toBeGreaterThan(defender)
      expect(defender).toBeGreaterThan(equal)
      expect(equal).toBeGreaterThan(forward)
    }
    for (const role of ['defender2', 'defender3'])
      expect(await y(names[`${color}_${role}`])).toBeCloseTo(defender)
    for (const role of ['equal2', 'equal3'])
      expect(await y(names[`${color}_${role}`])).toBeCloseTo(equal)
    const substitute = token(names[`${color}_substitute`])
    expect(await y(names[`${color}_substitute`])).toBeCloseTo(keeper)
    expect(
      await substitute.evaluate((el) => parseFloat((el as HTMLElement).style.left)),
    ).toBeCloseTo(color === 'black' ? 86 : 14)
  }
  await page.setViewportSize({ width: 390, height: 844 })
  await page.screenshot({ path: 'test-results/tactics-331-mobile.png', fullPage: true })
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  await page.setViewportSize({ width: 1440, height: 1600 })
  const player = names.black_defender
  const handle = page.getByRole('button', { name: `Перетащить: ${player}`, exact: true })
  const from = await handle.boundingBox(),
    pitch = await page.locator('.tactics-pitch').boundingBox()
  expect(from && pitch).toBeTruthy()
  await page.mouse.move(from!.x + from!.width / 2, from!.y + from!.height / 2)
  await page.mouse.down()
  await page.mouse.move(pitch!.x + pitch!.width * 0.27, pitch!.y + pitch!.height * 0.72, {
    steps: 12,
  })
  await page.mouse.up()
  await expect(token(player)).toHaveClass(/white/)
  expect(await y(player)).toBeCloseTo(72, 0)
  await page.reload()
  await expect(token(player)).toHaveClass(/white/)
  expect(await y(player)).toBeCloseTo(72, 0)
  // Moving a token within its half preserves the team's score.
  const scores = await page.locator('.tactics-scores').innerText()
  await token(player)
    .getByRole('button', { name: `На поле: ${player}`, exact: true })
    .focus()
  await page.keyboard.press('ArrowLeft')
  expect(await page.locator('.tactics-scores').innerText()).toBe(scores)
  expect((await send(`/matches/${m.id}`)).registrations).toEqual(m.registrations)
  const adminContext = await browser.newContext()
  const admin = await adminContext.newPage()
  try {
    await admin.goto(`/?game=${m.id}&screen=lineup`)
    await admin.getByRole('button', { name: 'Войти администратором' }).click()
    await expect(
      admin.locator('.tactics-token').filter({
        has: admin.getByRole('button', { name: `На поле: ${player}`, exact: true }),
      }),
    ).toHaveClass(/black/)
    await admin.getByRole('button', { name: 'Утвердить состав', exact: true }).click()
    await expect(admin.getByRole('status').filter({ hasText: 'Состав утверждён' })).toBeVisible()
    await page.reload()
    await expect(
      page.getByRole('alert').filter({ hasText: 'Список или оценки изменились' }),
    ).toBeVisible()
  } finally {
    await adminContext.close()
  }
  await page.getByText('Действия и подробности', { exact: true }).click()
  await page.getByRole('button', { name: 'Вернуть общий состав', exact: true }).click()
  await expect(token(player)).toHaveClass(/black/)
  await page.setViewportSize({ width: 390, height: 844 })
  // Tap-to-place is available without a drag gesture on a narrow screen.
  await page.getByRole('button', { name: `Перетащить: ${player}`, exact: true }).click()
  await expect(
    page.getByRole('status').filter({ hasText: `Куда поставить ${player}?` }),
  ).toBeVisible()
  const mobilePitch = await page.locator('.tactics-pitch').boundingBox()
  // Use open space near the goal, away from the three defender tokens.
  await page.locator('.tactics-pitch').click({
    position: { x: mobilePitch!.width * 0.7, y: mobilePitch!.height * 0.89 },
  })
  await expect(token(player)).toHaveClass(/white/)
  expect(await y(player)).toBeCloseTo(89, 0)
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  await page.screenshot({ path: 'test-results/tactics-mobile-placement.png', fullPage: true })
  const originalTemplate = await send('/template')
  try {
    await send('/template', 'PUT', {
      ...originalTemplate,
      extended_chat_id: '-1001247505259',
    })
    await page.reload()
    const share = page.getByRole('button', { name: 'Поделиться в чат', exact: true })
    await expect(share).toBeEnabled()
    const shared = page.waitForResponse(
      (r) => r.url().endsWith(`/matches/${m.id}/lineup/share`) && r.request().method() === 'POST',
    )
    await share.click()
    expect((await shared).ok()).toBe(true)
    await expect(
      page.getByRole('status').filter({ hasText: 'Состав поставлен в очередь' }),
    ).toBeVisible()
    const beforeClear = await send(`/matches/${m.id}`)
    expect(
      beforeClear.publications.filter((p: { kind: string }) => p.kind === 'lineup_share'),
    ).toHaveLength(1)
    await page.getByRole('button', { name: 'Очистить доску', exact: true }).click()
    await expect(page.locator('.tactics-token')).toHaveCount(0)
    await expect(
      page.getByText('Выберите вариант или добавьте игроков из списка', { exact: true }),
    ).toBeVisible()
    await expect(share).toBeDisabled()
    await page.reload()
    await expect(page.locator('.tactics-empty')).toBeVisible()
    await expect(page.locator('.tactics-token')).toHaveCount(0)
    const afterClear = await send(`/matches/${m.id}`)
    expect(afterClear.registrations).toEqual(beforeClear.registrations)
    expect(afterClear.version).toBe(beforeClear.version)
    for (const width of [320, 390]) {
      await page.setViewportSize({ width, height: 844 })
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
        true,
      )
    }
    await page.screenshot({ path: 'test-results/tactics-clear-mobile.png', fullPage: true })
  } finally {
    const current = await send('/template')
    await send('/template', 'PUT', { ...originalTemplate, version: current.version })
  }
})
