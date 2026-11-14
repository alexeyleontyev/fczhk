import { expect, test, type Page } from './app-test'

async function openLine(page: Page, index: number, freezeVersion = false) {
  const adminLogin = await page.request.post('/api/auth/demo/admin')
  expect(adminLogin.status()).toBe(200)
  const admin = await adminLogin.json()
  const headers = { Authorization: `Bearer ${admin.token}` }
  const playerLogin = await page.request.post('/api/auth/demo/player')
  expect(playerLogin.status()).toBe(200)
  const player = await playerLogin.json()
  const matches = await page.request.get('/api/matches?limit=100', { headers })
  expect(matches.status()).toBe(200)
  const fixture = (await matches.json()).find(
    (match: { location: string }) => match.location === `Линия ставок · ${index}`,
  )
  expect(fixture).toBeDefined()
  const id: number = fixture.id
  await page
    .context()
    .addInitScript((token) => sessionStorage.setItem('fczhk-session', token), player.token)
  if (freezeVersion) {
    // Simulate another administrator updating the game between background polls.
    const response = await page.request.get(`/api/matches/${id}`, { headers })
    expect(response.status()).toBe(200)
    const current = await response.json()
    await page.route(`**/api/matches/${id}`, (route) => route.fulfill({ json: current }))
  }
  await page.goto(`/?game=${id}`)
  const loaded = page.waitForResponse((r) => r.url().endsWith(`/api/matches/${id}/odds`))
  await page
    .getByRole('navigation', { name: 'Главная навигация' })
    .getByRole('button', { name: 'Ставки', exact: true })
    .click()
  const original = await (await loaded).json()
  expect(original.available).toBe(true)
  await expect(page.locator('.odds-button').first()).toBeEnabled()
  return { id, headers, original }
}

async function swapColors(page: Page, id: number, headers: Record<string, string>) {
  const match = await (await page.request.get(`/api/matches/${id}`, { headers })).json()
  const changed = await page.request.post(`/api/matches/${id}/teams/swap-colors`, {
    headers,
    data: { version: match.version },
  })
  expect(changed.status()).toBe(200)
  const line = await page.request.get(`/api/matches/${id}/odds`, { headers })
  expect(line.status()).toBe(200)
  return line.json()
}

function nextQuote(page: Page, id: number, oddsId: number) {
  return page.waitForResponse(
    (r) =>
      r.url().endsWith(`/api/matches/${id}/odds/quote`) &&
      r.status() === 200 &&
      r.request().postDataJSON().odds_id === oddsId,
    { timeout: 6000 },
  )
}

async function selectWhite(page: Page, id: number, oddsId: number) {
  const response = nextQuote(page, id, oddsId)
  await page.locator('.odds-button').filter({ hasText: 'Победа белых' }).click()
  const quote = await (await response).json()
  expect(quote.odds_id).toBe(oddsId)
  await expect(page.getByRole('button', { name: /Поставить/ })).toBeEnabled()
}

async function place(page: Page, id: number, oddsId: number) {
  const placed = page.waitForResponse((r) => r.url().endsWith(`/api/matches/${id}/bets`))
  await page.getByRole('button', { name: /Поставить/ }).click()
  const response = await placed
  expect(response.request().postDataJSON().odds_id).toBe(oddsId)
  expect(response.status()).toBe(201)
  const result = await response.json()
  expect(result.bet.status).toBe('open')
  expect(result.bet.stake).toBe(10)
}

test('updates the line after the match version changes without reopening the tab', async ({
  page,
}) => {
  const { id, headers, original } = await openLine(page, 0)
  const current = await swapColors(page, id, headers)
  expect(current.odds_id).not.toBe(original.odds_id)
  const reload = page.waitForResponse((r) => r.url().endsWith(`/api/matches/${id}/odds`), {
    timeout: 6000,
  })
  // The app performs its normal background match refresh when connectivity returns.
  await page.evaluate(() => window.dispatchEvent(new Event('online')))
  expect((await (await reload).json()).odds_id).toBe(current.odds_id)
  await selectWhite(page, id, current.odds_id)
  await place(page, id, current.odds_id)
})

test('refresh button reloads the line and requotes the existing slip', async ({ page }) => {
  const { id, headers, original } = await openLine(page, 1, true)
  await selectWhite(page, id, original.odds_id)
  const current = await swapColors(page, id, headers)
  const quote = nextQuote(page, id, current.odds_id)
  await page.getByRole('button', { name: 'Обновить', exact: true }).click()
  expect((await (await quote).json()).odds_id).toBe(current.odds_id)
  await expect(page.getByRole('region', { name: 'Купон', exact: true })).toContainText(
    'Победа белых',
  )
  await place(page, id, current.odds_id)
})

test('quote conflict reloads the line and restores betting before the next match poll', async ({
  page,
}) => {
  const { id, headers, original } = await openLine(page, 2, true)
  const current = await swapColors(page, id, headers)
  const stale = page.waitForResponse(
    (r) => r.url().endsWith(`/api/matches/${id}/odds/quote`) && r.status() === 409,
  )
  const fresh = nextQuote(page, id, current.odds_id)
  await page.locator('.odds-button').filter({ hasText: 'Победа белых' }).click()
  expect((await stale).request().postDataJSON().odds_id).toBe(original.odds_id)
  expect((await (await fresh).json()).odds_id).toBe(current.odds_id)
  await expect(page.getByRole('button', { name: /Поставить/ })).toBeEnabled()
  await place(page, id, current.odds_id)
})

test('bet conflict reloads the line and allows resubmission with the current odds', async ({
  page,
}) => {
  const { id, headers, original } = await openLine(page, 3, true)
  await selectWhite(page, id, original.odds_id)
  const current = await swapColors(page, id, headers)
  const stale = page.waitForResponse(
    (r) => r.url().endsWith(`/api/matches/${id}/bets`) && r.status() === 409,
  )
  const fresh = nextQuote(page, id, current.odds_id)
  await page.getByRole('button', { name: /Поставить/ }).click()
  expect((await stale).request().postDataJSON().odds_id).toBe(original.odds_id)
  expect((await (await fresh).json()).odds_id).toBe(current.odds_id)
  await expect(page.getByRole('button', { name: /Поставить/ })).toBeEnabled()
  await place(page, id, current.odds_id)
})
