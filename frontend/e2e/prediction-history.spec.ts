import { expect, test } from '@playwright/test'

test('standings show historical forecast counts and average points at mobile and desktop widths', async ({
  page,
  request,
}) => {
  const member = await (await request.post('/api/auth/demo/player')).json()
  const rows = [
    {
      rank: 1,
      player_id: 9001,
      alias: 'Нави',
      points: 11,
      baseline_points: 11,
      baseline_predictions: 8,
      predictions: 8,
      settled: 8,
      average_points: 1.375,
    },
    {
      rank: 2,
      player_id: 9002,
      alias: 'Виталя Легенда 17',
      points: 5,
      baseline_points: 5,
      baseline_predictions: 5,
      predictions: 5,
      settled: 5,
      average_points: 1,
    },
    {
      rank: 3,
      player_id: 9003,
      alias: 'Нулевой результат',
      points: 0,
      baseline_points: 0,
      baseline_predictions: 1,
      predictions: 1,
      settled: 1,
      average_points: 0,
    },
    {
      rank: 3,
      player_id: member.player.id,
      alias: member.player.alias,
      points: 0,
      baseline_points: 0,
      baseline_predictions: 0,
      predictions: 0,
      settled: 0,
      average_points: null,
    },
  ].map((row) => ({ ...row, three_points: 0, two_points: 0, one_point: 0, half_points: 0 }))
  await page.route('**/api/predictions/standings*', (route) => route.fulfill({ json: rows }))
  await page.addInitScript((token) => sessionStorage.setItem('fczhk-session', token), member.token)
  await page.goto('/')
  await page.getByRole('button', { name: 'Прогнозы', exact: true }).click()
  const table = page.locator('.standings-table')
  const navi = table.getByRole('row').filter({ hasText: 'Нави' })
  await expect(navi.locator('td').nth(2)).toHaveText('8')
  await expect(navi.locator('td').nth(3)).toHaveText('1,38')
  const vitaly = table.getByRole('row').filter({ hasText: 'Виталя Легенда 17' })
  await expect(vitaly.locator('td').nth(2)).toHaveText('5')
  await expect(vitaly.locator('td').nth(3)).toHaveText('1')
  await expect(vitaly.locator('td').last()).toHaveText('5')
  await navi.locator('summary').click()
  await expect(navi).toContainText('Из таблицы: 8 прогнозов, стартовые очки: 11')
  await expect(navi).toContainText('Учтено 8 из 8')
  const zero = table.getByRole('row').filter({ hasText: 'Нулевой результат' })
  await expect(zero.locator('td').nth(3)).toHaveText('0')
  const empty = table.locator('tr.mine')
  await expect(empty.locator('td').nth(2)).toHaveText('0')
  await expect(empty.locator('td').nth(3)).toHaveText('—')
  for (const width of [320, 390, 1440]) {
    await page.setViewportSize({ width, height: 900 })
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
    const points = await vitaly.locator('td').last().boundingBox()
    expect(points!.x + points!.width).toBeLessThanOrEqual(width)
    await page.screenshot({ path: `test-results/prediction-history-${width}.png`, fullPage: true })
  }
})
