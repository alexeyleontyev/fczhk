import { test, expect } from '@playwright/test'

test('mobile result: unknown goals, actual rosters, corrections and player statistics', async ({
  page,
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
  const day = new Date(Date.UTC(1970, 0, 1) + Math.floor(Math.random() * 12000) * 86400000)
    .toISOString()
    .slice(0, 10)
  let m = await send('/matches', 'POST', {
    starts_at: `${day}T20:00:00+03:00`,
    location: 'Результаты MVP 3',
  })
  for (const p of [white, black])
    m = await send(`/matches/${m.id}/participants`, 'POST', {
      version: m.version,
      player_id: p.id,
      position: 'field',
    })
  for (const action of ['open', 'finalize'])
    m = await send(`/matches/${m.id}/actions/${action}`, 'POST', { version: m.version })
  m = await send(`/matches/${m.id}/teams`, 'PUT', {
    version: m.version,
    assignments: Object.fromEntries(
      m.registrations.map((r: { id: number; player_id: number }) => [
        r.id,
        r.player_id === white.id ? 'white' : 'black',
      ]),
    ),
  })
  m = await send(`/matches/${m.id}/actions/approve`, 'POST', { version: m.version })
  await page.goto(`/?game=${m.id}`)
  await page.getByRole('button', { name: 'Войти администратором' }).click()
  await page.getByRole('tab', { name: 'Итог', exact: true }).click()
  const result = page.locator('.result-panel')
  await result.getByRole('button', { name: 'Внести результат', exact: true }).click()
  await result.getByRole('button', { name: 'Гол: ⚪ Белые', exact: true }).click()
  await result.getByRole('button', { name: 'Сохранить черновик' }).click()
  await expect(result.getByText('Черновик', { exact: true })).toBeVisible()
  await expect(result).toHaveCount(1)
  await result.getByRole('button', { name: 'Исправить результат' }).click()
  await result
    .getByRole('combobox', { name: 'Автор гола', exact: true })
    .selectOption(String(white.id))
  await result.getByRole('button', { name: 'Завершить матч', exact: true }).click()
  await expect(page.locator('.archive-scoreboard')).toContainText('1 : 0')
  await expect(page.getByRole('heading', { name: 'Сбор на игру', exact: true })).toHaveCount(0)
  await page.getByRole('button', { name: 'История изменений', exact: true }).click()
  await expect(page.getByRole('region', { name: 'История изменений', exact: true })).toContainText(
    'Сохранён результат',
  )
  await page.getByRole('button', { name: 'Исправить результат', exact: true }).click()
  await result.getByRole('button', { name: 'Гол: ⚫ Чёрные', exact: true }).click()
  await result
    .getByRole('combobox', { name: 'Тип гола', exact: true })
    .last()
    .selectOption('own_goal')
  await expect(
    result.getByRole('combobox', { name: 'Автор гола', exact: true }).last(),
  ).toHaveValue('')
  await result.getByRole('button', { name: 'Сохранить исправления', exact: true }).click()
  await expect(page.locator('.archive-scoreboard')).toContainText('1 : 1')
  await expect(page.locator('.archive-goals').getByText('Автогол', { exact: true })).toBeVisible()
  await page.screenshot({ path: 'test-results/mvp3-result-mobile.png', fullPage: true })
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  await page.getByRole('button', { name: 'Профиль', exact: true }).click()
  await expect(
    page.getByRole('heading', { name: 'Статистика: Алексей', exact: true }),
  ).toBeVisible()
  await page
    .getByRole('combobox', { name: 'Период статистики', exact: true })
    .selectOption(m.season)
  await page.getByRole('tab', { name: 'Матчи', exact: true }).click()
  await page.locator('.statistics .stat-link').filter({ hasText: '1 : 1' }).first().click()
  await expect(page.locator('.archive-scoreboard')).toContainText('1 : 1')
  await page.getByRole('button', { name: 'Сменить роль', exact: true }).click()
  await page.getByRole('button', { name: 'Войти игроком', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Исправить результат', exact: true })).toHaveCount(
    0,
  )
  await expect(page.locator('.archive-scoreboard')).toContainText('1 : 1')
})
