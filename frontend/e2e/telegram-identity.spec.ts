import { expect, test } from '@playwright/test'

for (const username of [null, 'long_telegram_username_12345678901']) {
  test(`Telegram profile identification and alias rename: ${username ?? 'ID fallback'}`, async ({
    page,
  }) => {
    const { token, player } = await (await page.request.post('/api/auth/demo/player')).json()
    const headers = { Authorization: `Bearer ${token}` }
    const me = await (await page.request.get('/api/me', { headers })).json()
    const nickname = `Игрок TG ${username ? 'никнейм' : 'ID'}`
    const rename = await page.request.patch('/api/me', { headers, data: { alias: nickname } })
    expect(rename.ok()).toBe(true)
    // Verified metadata capture is tested through the real backend auth flows.
    // Only Telegram's optional nickname is injected here; IDs and alias use the demo DB.
    await page.route('**/api/me', async (route) => {
      const response = await route.fetch()
      await route.fulfill({ json: { ...(await response.json()), telegram_username: username } })
    })
    await page.route(`**/api/players/${player.id}/stats*`, async (route) => {
      const response = await route.fetch()
      await route.fulfill({ json: { ...(await response.json()), telegram_username: username } })
    })
    await page.addInitScript((value) => sessionStorage.setItem('fczhk-session', value), token)
    await page.setViewportSize({ width: 320, height: 780 })
    try {
      await page.goto('/')
      await page.getByRole('button', { name: 'Профиль', exact: true }).click()
      const identity = page.locator('[aria-label="Аккаунт Telegram"]')
      await expect(identity).toHaveCount(1)
      await expect(page.getByRole('heading', { name: nickname, exact: true })).toBeVisible()
      if (username) {
        await expect(identity.getByRole('link')).toHaveText(`@${username}`)
        await expect(identity.getByRole('link')).toHaveAttribute('href', `https://t.me/${username}`)
        await expect(identity).not.toContainText('Telegram ID:')
      } else {
        await expect(identity).toHaveText(`Telegram ID: ${me.telegram_id}`)
        await expect(identity.getByRole('link')).toHaveCount(0)
      }
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
        true,
      )
      await page.screenshot({
        path: `test-results/profile-telegram-${username ? 'username' : 'id'}.png`,
        fullPage: true,
      })
      await page.getByRole('button', { name: 'Игроки', exact: true }).click()
      await page.getByLabel('Поиск игроков', { exact: true }).fill(nickname)
      await page
        .locator('.catalog-person')
        .getByRole('button', { name: nickname, exact: true })
        .click()
      const dialog = page.getByRole('dialog')
      await expect(
        dialog.getByRole('heading', { name: `Статистика: ${nickname}`, exact: true }),
      ).toBeVisible()
      await expect(dialog.locator('[aria-label="Аккаунт Telegram"]')).toHaveText(
        username ? `@${username}` : `Telegram ID: ${me.telegram_id}`,
      )
    } finally {
      await page.request.patch('/api/me', { headers, data: { alias: me.alias } })
    }
  })
}
