import { test, expect } from '@playwright/test'

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
    for (const role of ['forward', 'defender', 'equal', 'keeper']) {
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
        attack: role === 'keeper' ? null : role === 'forward' ? 5 : 2,
        defense: role === 'defender' ? 5 : 2,
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
  await expect(page.locator('.tactics-token')).toHaveCount(8)
  await expect(page.getByRole('button', { name: 'Утвердить состав', exact: true })).toHaveCount(0)
  const token = (name: string) =>
    page.getByRole('button', { name: `На поле: ${name}`, exact: true })
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
  }
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
  await token(player).focus()
  await page.keyboard.press('ArrowLeft')
  expect(await page.locator('.tactics-scores').innerText()).toBe(scores)
  expect((await send(`/matches/${m.id}`)).registrations).toEqual(m.registrations)
  const adminContext = await browser.newContext()
  const admin = await adminContext.newPage()
  try {
    await admin.goto(`/?game=${m.id}&screen=lineup`)
    await admin.getByRole('button', { name: 'Войти администратором' }).click()
    await expect(
      admin.getByRole('button', { name: `На поле: ${player}`, exact: true }),
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
  await page.getByRole('button', { name: player, exact: true }).click()
  await expect(
    page.getByRole('status').filter({ hasText: `Куда поставить ${player}?` }),
  ).toBeVisible()
  await page.locator('.tactics-pitch').click({ position: { x: 100, y: 320 } })
  await expect(token(player)).toHaveClass(/white/)
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  await page.screenshot({ path: 'test-results/tactics-mobile-placement.png', fullPage: true })
})
