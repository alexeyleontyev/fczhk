import { expect, test } from '@playwright/test'

test('owner grants and revokes administrator access while protecting owner role', async ({
  page,
  browser,
  request,
}) => {
  const player = await (await request.post('/api/auth/demo/player')).json()
  const playerHeaders = { Authorization: `Bearer ${player.token}` }
  await page.goto('/')
  await page.getByRole('button', { name: 'Войти администратором' }).click()
  await expect(page.locator('.user-chip small')).toHaveText('Владелец')
  const ownerToken = await page.evaluate(() => sessionStorage.getItem('fczhk-session'))
  const ownerHeaders = { Authorization: `Bearer ${ownerToken}` }
  await page.getByRole('button', { name: 'Настройки', exact: true }).click()
  const panel = page.getByRole('region', { name: 'Администраторы', exact: true })
  await expect(panel.getByText('Владелец · Telegram ID 1001')).toBeVisible()
  await expect(panel.getByRole('button', { name: 'Снять права' })).toHaveCount(0)
  await panel.getByLabel('Новый администратор').selectOption(String(player.player.id))
  await panel.getByRole('button', { name: 'Назначить администратором' }).click()
  await expect(panel.getByRole('status')).toContainText('назначен администратором')
  expect((await request.get('/api/template', { headers: playerHeaders })).status()).toBe(200)
  expect((await request.get('/api/administrators', { headers: playerHeaders })).status()).toBe(403)
  const context = await browser.newContext({ viewport: { width: 390, height: 844 } })
  try {
    await context.addInitScript(
      (token) => sessionStorage.setItem('fczhk-session', token),
      player.token,
    )
    const adminPage = await context.newPage()
    await adminPage.goto('/')
    await expect(adminPage.locator('.user-chip small')).toHaveText('Администратор')
    await adminPage.getByRole('button', { name: 'Настройки', exact: true }).click()
    await expect(adminPage.getByRole('heading', { name: 'Доставка сообщений' })).toBeVisible()
    await expect(
      adminPage.getByRole('region', { name: 'Администраторы', exact: true }),
    ).toHaveCount(0)
    await panel.screenshot({ path: 'test-results/administrators-mobile.png' })
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
    page.once('dialog', (dialog) => dialog.accept())
    await panel.getByRole('button', { name: 'Снять права' }).click()
    await expect(panel.getByRole('status')).toContainText('сняты')
    expect((await request.get('/api/template', { headers: playerHeaders })).status()).toBe(403)
    await adminPage.reload()
    await expect(adminPage.locator('.user-chip small')).toHaveText('Игрок')
    await expect(adminPage.getByRole('button', { name: 'Настройки', exact: true })).toHaveCount(0)
  } finally {
    await context.close()
    const users = await (await request.get('/api/administrators', { headers: ownerHeaders })).json()
    const current = users.find((user: { id: number }) => user.id === player.player.id)
    if (current?.role === 'admin') {
      await request.put(`/api/administrators/${current.id}`, {
        headers: ownerHeaders,
        data: { is_admin: false, revision: current.revision },
      })
    }
  }
})
