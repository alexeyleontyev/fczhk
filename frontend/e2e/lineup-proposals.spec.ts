import { test, expect } from '@playwright/test'

test('teams precede field, edits are private, proposals are shared and approval keeps authorship', async ({
  page,
  browser,
  request,
}) => {
  const adminAuth = await (await request.post('/api/auth/demo/admin')).json()
  const playerAuth = await (await request.post('/api/auth/demo/player')).json()
  async function send(path: string, method = 'GET', data?: object, token = adminAuth.token) {
    const response = await request.fetch('/api' + path, {
      method,
      data,
      headers: { Authorization: `Bearer ${token}` },
    })
    expect(response.ok(), await response.text()).toBe(true)
    return response.json()
  }
  const stamp = Date.now(),
    member = await send('/me', 'GET', undefined, playerAuth.token)
  let match = await send('/matches', 'POST', {
    starts_at: '2096-05-21T20:00:00+03:00',
    location: `Предложения ${stamp}`,
  })
  for (let i = 0; i < 8; i++) {
    const p = await send('/players/guests', 'POST', { alias: `Вариант ${i + 1} ${stamp}` })
    const position = i >= 6 ? 'keeper' : 'field'
    match = await send(`/matches/${match.id}/participants`, 'POST', {
      version: match.version,
      player_id: p.id,
      position,
    })
    await send(`/players/${p.id}/ratings`, 'PUT', {
      position,
      attack: position === 'keeper' ? null : [5, 4, 3, 2, 1, 0][i],
      defense: position === 'keeper' ? 4 : [5, 3, 2, 2, 1, 0][i],
      revision: 0,
    })
  }
  for (const action of ['open', 'finalize'])
    match = await send(`/matches/${match.id}/actions/${action}`, 'POST', { version: match.version })
  match = await send(`/matches/${match.id}/teams`, 'PUT', {
    version: match.version,
    assignments: Object.fromEntries(
      match.registrations.map((r: { id: number }, i: number) => [r.id, i % 2 ? 'black' : 'white']),
    ),
  })
  const before = await send(`/matches/${match.id}`)
  await page.addInitScript(
    (token) => sessionStorage.setItem('fczhk-session', token),
    playerAuth.token,
  )
  await page.goto(`/?game=${match.id}&screen=lineup`)
  const tabs = page.getByRole('tablist', { name: 'Экраны игры' })
  await expect(tabs.getByRole('tab')).toHaveText(['Игра', 'Команды', 'Поле'])
  const picker = page.getByLabel('Вариант состава')
  await picker.selectOption('community')
  await expect(page.getByLabel('Белая команда').locator('.lineup-player-row')).toHaveCount(4)
  await expect(page.getByRole('button', { name: 'Предложить состав', exact: true })).toBeDisabled()
  await page.getByRole('button', { name: 'Взять за основу', exact: true }).click()
  const comparison = page.getByRole('region', { name: 'Сравнение оценок составов', exact: true })
  const upperValues = comparison
    .getByRole('region', { name: 'Основные оценки', exact: true })
    .locator('.lineup-rating-metrics b')
  const beforeScores = await upperValues.allTextContents()
  const white = page.getByLabel('Белая команда', { exact: true }),
    black = page.getByLabel('Чёрная команда', { exact: true })
  const first = white.locator('.lineup-player-row').first()
  const alias = await first.locator('.player-name').innerText()
  const originalColor = await first.evaluate((e) => getComputedStyle(e).backgroundColor)
  const handle = first.getByRole('button', { name: /^Перетащить:/ })
  await handle.scrollIntoViewIfNeeded()
  const from = await handle.boundingBox(),
    drop = await black.locator('.lineup-player-row').first().boundingBox()
  expect(from && drop).toBeTruthy()
  await page.mouse.move(from!.x + from!.width / 2, from!.y + from!.height / 2)
  await page.mouse.down()
  await page.mouse.move(drop!.x + drop!.width / 2, drop!.y + drop!.height / 2, { steps: 12 })
  await page.mouse.up()
  await expect(black.locator('.lineup-player-row').filter({ hasText: alias })).toHaveCount(1)
  expect(await upperValues.allTextContents()).not.toEqual(beforeScores)
  await expect(page.getByRole('button', { name: 'Предложить состав', exact: true })).toBeDisabled()
  const moved = black.locator('.lineup-player-row').filter({ hasText: alias })
  expect(await moved.evaluate((e) => getComputedStyle(e).backgroundColor)).toBe(originalColor)
  await page.getByRole('tab', { name: 'Поле', exact: true }).click()
  await expect(page.locator('.tactics-token.black').filter({ hasText: alias })).toBeVisible()
  await expect(comparison).not.toBeVisible()
  await page.getByRole('tab', { name: 'Команды', exact: true }).click()
  await moved.getByRole('button', { name: /перевести в белые/ }).click()
  expect(await upperValues.allTextContents()).toEqual(beforeScores)
  expect((await send(`/matches/${match.id}`)).registrations).toEqual(before.registrations)
  for (const width of [320, 360, 390, 768, 1440]) {
    await page.setViewportSize({ width, height: 1000 })
    const w = await white.boundingBox(),
      b = await black.boundingBox()
    expect(w && b).toBeTruthy()
    expect(b!.x).toBeGreaterThan(w!.x + w!.width)
    expect(Math.abs(w!.y - b!.y)).toBeLessThan(2)
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
    await page.screenshot({
      path: `test-results/lineup-team-proposals-${width}.png`,
      fullPage: true,
    })
  }
  await page.getByRole('button', { name: 'Предложить состав', exact: true }).click()
  await expect(page.getByRole('status').filter({ hasText: 'Ваш вариант доступен' })).toBeVisible()
  let list = await send(`/matches/${match.id}/lineup/proposals`)
  expect(list.proposals).toHaveLength(1)
  const proposal = list.proposals[0]
  expect(proposal.author_id).toBe(member.id)
  expect((await send(`/matches/${match.id}`)).version).toBe(before.version)
  await page.getByRole('button', { name: 'Взять за основу', exact: true }).click()
  await page.getByRole('button', { name: 'Обновить предложение', exact: true }).click()
  await expect(page.getByRole('status').filter({ hasText: 'Предложение обновлено' })).toBeVisible()
  list = await send(`/matches/${match.id}/lineup/proposals`)
  expect(list.proposals).toHaveLength(1)
  expect(list.proposals[0].revision).toBe(2)

  const adminContext = await browser.newContext()
  try {
    await adminContext.addInitScript(
      (token) => sessionStorage.setItem('fczhk-session', token),
      adminAuth.token,
    )
    const admin = await adminContext.newPage()
    await admin.goto(`/?game=${match.id}&screen=lineup`)
    await admin.getByLabel('Вариант состава').selectOption(`proposal:${proposal.id}`)
    await admin.getByRole('button', { name: 'Утвердить состав', exact: true }).click()
    await expect(admin.getByRole('status').filter({ hasText: 'Состав утверждён' })).toBeVisible()
    await expect(admin.getByLabel('Вариант состава')).toHaveValue('official')
    expect((await send(`/matches/${match.id}`)).status).toBe('approved')
    const history = await send(`/matches/${match.id}/history`)
    const confirmation = history.audit.find(
      (e: { action: string }) => e.action === 'lineup.confirmed',
    )
    expect(confirmation.data.author_id).toBe(member.id)
    expect(confirmation.data.proposal_id).toBe(proposal.id)
    // Official teams are always the default, including when a private local draft exists.
    await admin.getByRole('button', { name: 'Взять за основу', exact: true }).click()
    await admin.reload()
    await expect(admin.getByLabel('Вариант состава')).toHaveValue('official')
  } finally {
    await adminContext.close()
  }
})
