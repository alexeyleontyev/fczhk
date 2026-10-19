import { test, expect } from '@playwright/test'
import { randomUUID } from 'node:crypto'

test('player outside roster: predict, revise, lock at kickoff and update overall standings', async ({
  page,
  request,
}) => {
  test.setTimeout(60000)
  const adminAuth = await (await request.post('/api/auth/demo/admin')).json()
  const playerAuth = await (await request.post('/api/auth/demo/player')).json()
  const headers = { Authorization: `Bearer ${adminAuth.token}` }
  const playerHeaders = { Authorization: `Bearer ${playerAuth.token}` }
  async function send(path: string, method = 'GET', data?: object) {
    const response = await request.fetch(`/api${path}`, { method, headers, data })
    expect(response.ok(), await response.text()).toBe(true)
    return response.json()
  }
  const guest = await send('/players/guests', 'POST', { alias: 'Игрок для прогнозов' })
  const starts = new Date(Date.now() + 22000).toISOString()
  let m = await send('/matches', 'POST', { starts_at: starts, location: 'Конкурс прогнозов' })
  for (const player of [adminAuth.player, guest])
    m = await send(`/matches/${m.id}/participants`, 'POST', {
      version: m.version,
      player_id: player.id,
      position: 'field',
    })
  for (const action of ['open', 'finalize'])
    m = await send(`/matches/${m.id}/actions/${action}`, 'POST', { version: m.version })
  await page.goto(`/?game=${m.id}`)
  await page.getByRole('button', { name: 'Войти игроком', exact: true }).click()
  await page.getByText('Прогноз на игру', { exact: true }).click()
  const panel = page.locator('.prediction-panel')
  await expect(
    panel.getByText('Прогнозы откроются после утверждения составов', { exact: true }),
  ).toBeVisible()
  await expect(panel.getByRole('button', { name: 'Сделать прогноз' })).toHaveCount(0)
  m = await send(`/matches/${m.id}/teams`, 'PUT', {
    version: m.version,
    assignments: Object.fromEntries(
      m.registrations.map((r: { id: number; player_id: number }) => [
        r.id,
        r.player_id === guest.id ? 'black' : 'white',
      ]),
    ),
  })
  m = await send(`/matches/${m.id}/actions/approve`, 'POST', { version: m.version })
  await page.reload()
  await page.getByText('Прогноз на игру', { exact: true }).click()
  await panel.getByLabel('Голы белых', { exact: true }).fill('3')
  await panel.getByLabel('Голы чёрных', { exact: true }).fill('1')
  await panel.getByRole('button', { name: 'Сделать прогноз', exact: true }).click()
  await expect(panel.getByText('Ваш прогноз: 3 : 1', { exact: true })).toBeVisible()
  await expect(panel.getByRole('button', { name: 'Изменить прогноз', exact: true })).toBeEnabled()
  await panel.getByLabel('Голы белых', { exact: true }).fill('4')
  await panel.getByLabel('Голы чёрных', { exact: true }).fill('2')
  await panel.getByRole('button', { name: 'Изменить прогноз', exact: true }).click()
  await expect(panel.getByText('Ваш прогноз: 4 : 2', { exact: true })).toBeVisible()
  const hidden = await send(`/matches/${m.id}/predictions`)
  expect(hidden.forecasts).toEqual([])
  await send(`/matches/${m.id}/prediction`, 'PUT', {
    white_score: 0,
    black_score: 0,
    approved_version: hidden.approved_version,
    revision: 0,
  })
  await page.screenshot({ path: 'test-results/mvp5-prediction-mobile.png', fullPage: true })
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  await expect(panel.getByText('Приём прогнозов завершён', { exact: true })).toBeVisible({
    timeout: 30000,
  })
  await expect(panel.getByRole('button', { name: 'Изменить прогноз', exact: true })).toHaveCount(0)
  const late = await request.put(`/api/matches/${m.id}/prediction`, {
    headers: playerHeaders,
    data: {
      white_score: 9,
      black_score: 0,
      approved_version: hidden.approved_version,
      revision: 2,
    },
  })
  expect(late.status()).toBe(409)
  const result = await send(`/matches/${m.id}/result`)
  let saved = await send(`/matches/${m.id}/result`, 'PUT', {
    version: result.version,
    completed: true,
    participants: result.participants.map(
      ({ player_id, team, position }: { player_id: number; team: string; position: string }) => ({
        player_id,
        team,
        position,
      }),
    ),
    goals: [0, 1].map(() => ({ id: randomUUID(), team: 'white' })),
  })
  await panel.getByRole('button', { name: 'Общий зачёт прогнозов', exact: true }).click()
  const row = page.locator('.standings-table tbody tr').filter({ hasText: 'Михаил' })
  await expect(row.locator('td').last()).toHaveText('3')
  await page.screenshot({ path: 'test-results/mvp5-standings-mobile.png', fullPage: true })
  await page.setViewportSize({ width: 320, height: 740 })
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  saved = await send(`/matches/${m.id}/result`, 'PUT', {
    version: saved.version,
    completed: true,
    participants: saved.participants.map(
      ({ player_id, team, position }: { player_id: number; team: string; position: string }) => ({
        player_id,
        team,
        position,
      }),
    ),
    goals: [...saved.goals, ...[0, 1].map(() => ({ id: randomUUID(), team: 'black' }))],
  })
  await page.getByRole('button', { name: 'Обновить зачёт', exact: true }).click()
  await expect(row.locator('td').last()).toHaveText('0')
  const winner = page.locator('.standings-table tbody tr').filter({ hasText: 'Алексей' })
  await expect(winner.locator('td').last()).toHaveText('1')
})
