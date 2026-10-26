import { expect, test } from '@playwright/test'

test('admin prepares a hidden collection and early players keep their queue when it opens', async ({
  page,
  request,
}) => {
  const admin = await (await request.post('/api/auth/demo/admin')).json()
  const player = await (await request.post('/api/auth/demo/player')).json()
  const headers = { Authorization: `Bearer ${admin.token}` }
  const memberHeaders = { Authorization: `Bearer ${player.token}` }
  const original = await (await request.get('/api/template', { headers })).json()
  const guest = await (
    await request.post('/api/players/guests', {
      headers,
      data: { alias: `Ранняя запись ${Date.now()}` },
    })
  ).json()
  const weekday = (new Date(Date.now() + 3 * 3600000).getUTCDay() + 6) % 7
  let id: number | null = null
  try {
    expect(
      (
        await request.put('/api/template', {
          headers,
          data: {
            ...original,
            enabled: true,
            opening_weekday: (weekday + 1) % 7,
            opening_time: '12:00',
            game_weekday: (weekday + 4) % 7,
            start_time: '20:00',
            location: 'Манеж предварительной записи',
          },
        })
      ).ok(),
    ).toBe(true)
    await page.addInitScript((token) => sessionStorage.setItem('fczhk-session', token), admin.token)
    await page.route('**/api/matches/current', (route) => route.fulfill({ json: null }))
    await page.goto('/')
    await page.getByRole('button', { name: 'Записать игроков заранее', exact: true }).click()
    const modal = page.getByRole('dialog', { name: 'Предварительная запись', exact: true })
    await expect(modal).toBeVisible()
    await expect(modal.getByLabel('Кого заменить', { exact: true })).toHaveCount(0)
    await modal
      .getByRole('combobox', { name: 'Игрок', exact: true })
      .selectOption(String(admin.player.id))
    await modal.getByRole('button', { name: 'Записать заранее', exact: true }).click()
    await expect(modal).toHaveCount(0)
    const urlId = new URL(page.url()).searchParams.get('game')
    id = Number(urlId)
    expect(id).toBeGreaterThan(0)
    await expect(
      page.getByRole('heading', { name: 'Предварительная запись', exact: true }),
    ).toBeVisible()
    await expect(page.locator('.status-pill')).toContainText('Запланирована')
    await expect(page.getByRole('timer')).toBeVisible()
    await expect(page.locator('.roster-main')).toContainText(admin.player.alias)
    await page.getByRole('button', { name: 'Добавить игрока', exact: true }).click()
    await modal.getByRole('combobox', { name: 'Игрок', exact: true }).selectOption(String(guest.id))
    await modal.getByRole('button', { name: 'Записать заранее', exact: true }).click()
    await expect(modal).toHaveCount(0)
    const hidden = await request.get(`/api/matches/${id}`, { headers: memberHeaders })
    expect(hidden.status()).toBe(404)
    const archive = await (
      await request.get('/api/matches?limit=100', { headers: memberHeaders })
    ).json()
    expect(archive.some((m: { id: number }) => m.id === id)).toBe(false)
    const before = await (await request.get(`/api/matches/${id}`, { headers })).json()
    expect(before.registrations.map((r: { player_id: number }) => r.player_id)).toEqual([
      admin.player.id,
      guest.id,
    ])
    expect(before.publications).toHaveLength(0)
    expect(
      before.registrations.every((r: { forced: boolean; paid: boolean }) => !r.forced && !r.paid),
    ).toBe(true)
    for (const width of [320, 390, 1440]) {
      await page.setViewportSize({ width, height: 900 })
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
        true,
      )
      await page.screenshot({
        path: `test-results/prepared-collection-${width}.png`,
        fullPage: true,
      })
    }
    await page.getByRole('button', { name: 'Открыть сбор', exact: true }).click()
    await expect(page.getByRole('button', { name: 'Утвердить составы', exact: true })).toBeVisible()
    const joined = await request.post(`/api/matches/${id}/join`, {
      headers: memberHeaders,
      data: { position: 'field' },
    })
    expect(joined.ok()).toBe(true)
    const opened = await joined.json()
    expect(opened.registrations.map((r: { player_id: number }) => r.player_id)).toEqual([
      admin.player.id,
      guest.id,
      player.player.id,
    ])
    expect(opened.registrations.slice(0, 2).map((r: { id: number }) => r.id)).toEqual(
      before.registrations.map((r: { id: number }) => r.id),
    )
  } finally {
    if (id) {
      const match = await (await request.get(`/api/matches/${id}`, { headers })).json()
      await request.post(`/api/matches/${id}/cancel`, {
        headers,
        data: { version: match.version, reason: 'Завершение браузерной проверки' },
      })
    }
    const current = await (await request.get('/api/template', { headers })).json()
    await request.put('/api/template', { headers, data: { ...original, version: current.version } })
  }
})
