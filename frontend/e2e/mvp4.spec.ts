import { test, expect } from '@playwright/test'

test('two captains: sealed bids, ties, free completion, approval and restart persistence', async ({
  page,
  browser,
  request,
}) => {
  const auth = await (await request.post('/api/auth/demo/admin')).json()
  const headers = { Authorization: `Bearer ${auth.token}` }
  async function send(path: string, method = 'GET', data?: object) {
    const response = await request.fetch(`/api${path}`, { method, headers, data })
    expect(response.ok(), await response.text()).toBe(true)
    return response.json()
  }
  const people = await send('/players')
  const white = people.find((p: { alias: string }) => p.alias === 'Алексей')
  const black = people.find((p: { alias: string }) => p.alias === 'Михаил')
  const guests = []
  for (let i = 0; i < 2; i++)
    guests.push(await send('/players/guests', 'POST', { alias: `Аукцион ${Date.now()} ${i}` }))
  const day = new Date(Date.UTC(2070, 0, 1) + Math.floor(Math.random() * 10000) * 86400000)
    .toISOString()
    .slice(0, 10)
  let m = await send('/matches', 'POST', {
    starts_at: `${day}T20:00:00+03:00`,
    location: 'Аукцион MVP 4',
  })
  for (const p of [white, black, ...guests])
    m = await send(`/matches/${m.id}/participants`, 'POST', {
      version: m.version,
      player_id: p.id,
      position: 'field',
    })
  for (const action of ['open', 'finalize'])
    m = await send(`/matches/${m.id}/actions/${action}`, 'POST', { version: m.version })
  await page.goto(`/?game=${m.id}`)
  await page.getByRole('button', { name: 'Войти администратором' }).click()
  const panel = page.locator('.auction-panel')
  const whiteCaptain = panel.getByLabel('Капитан: ⚪ Белые', { exact: true })
  const blackCaptain = panel.getByLabel('Капитан: ⚫ Чёрные', { exact: true })
  const startAuction = panel.getByRole('button', { name: 'Начать аукцион', exact: true })
  await expect(startAuction).toBeDisabled()
  await whiteCaptain.selectOption(String(black.id))
  await expect(blackCaptain.locator(`option[value="${black.id}"]`)).toHaveJSProperty(
    'disabled',
    true,
  )
  await expect(startAuction).toBeDisabled()
  await blackCaptain.selectOption(String(white.id))
  await expect(whiteCaptain.locator(`option[value="${white.id}"]`)).toHaveJSProperty(
    'disabled',
    true,
  )
  await expect(startAuction).toBeEnabled()
  await whiteCaptain.selectOption('')
  await expect(blackCaptain.locator(`option[value="${black.id}"]`)).toHaveJSProperty(
    'disabled',
    false,
  )
  await expect(startAuction).toBeDisabled()
  await blackCaptain.selectOption(String(black.id))
  await expect(whiteCaptain.locator(`option[value="${white.id}"]`)).toHaveJSProperty(
    'disabled',
    false,
  )
  await expect(whiteCaptain.locator(`option[value="${black.id}"]`)).toHaveJSProperty(
    'disabled',
    true,
  )
  await whiteCaptain.selectOption(String(white.id))
  await expect(startAuction).toBeEnabled()
  await startAuction.click()
  await expect(panel.getByText('Торги идут', { exact: true })).toBeVisible()
  const second = await browser.newContext({ viewport: { width: 390, height: 844 } })
  try {
    const other = await second.newPage()
    await other.goto(page.url())
    await other.getByRole('button', { name: 'Войти игроком', exact: true }).click()
    const blackPanel = other.locator('.auction-panel')
    await panel.getByLabel('Ваша закрытая ставка').fill('0')
    await panel.getByRole('button', { name: 'Подтвердить ставку' }).click()
    await expect(
      panel.getByText('Ваша ставка: 0. Изменить её нельзя.', { exact: true }),
    ).toBeVisible()
    await expect(
      blackPanel.getByText('Ваша ставка: 0. Изменить её нельзя.', { exact: true }),
    ).toHaveCount(0)
    await page.reload()
    await expect(
      panel.getByText('Ваша ставка: 0. Изменить её нельзя.', { exact: true }),
    ).toBeVisible()
    await blackPanel.getByLabel('Ваша закрытая ставка').fill('0')
    await blackPanel.getByRole('button', { name: 'Подтвердить ставку' }).click()
    await expect(panel.getByText('ЛОТ 2 · КРУГ 1', { exact: true })).toBeVisible()
    await panel.locator('summary').filter({ hasText: 'История лотов' }).click()
    await expect(panel.getByText('Равные ставки — перенос на следующий круг')).toBeVisible()
    await panel.getByLabel('Ваша закрытая ставка').fill('10')
    await panel.getByRole('button', { name: 'Подтвердить ставку' }).click()
    await blackPanel.getByLabel('Ваша закрытая ставка').fill('0')
    await blackPanel.getByRole('button', { name: 'Подтвердить ставку' }).click()
    await expect(panel.getByText('Команды собраны', { exact: true })).toBeVisible()
    await expect(panel.getByText(/Бесплатно после заполнения соперника/)).toBeVisible()
    await expect(page.getByRole('button', { name: 'Утвердить команды', exact: true })).toBeVisible()
    await page.getByRole('button', { name: 'Утвердить команды', exact: true }).click()
    await expect(page.getByText('Команды готовы', { exact: true })).toBeVisible()
    await page.screenshot({ path: 'test-results/mvp4-auction-mobile.png', fullPage: true })
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  } finally {
    await second.close()
  }
})
