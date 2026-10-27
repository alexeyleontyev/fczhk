import { test, expect } from '@playwright/test'
import { publicationState } from './confirmation-helpers'

test('lineup rating sources are independent, prefer rated participants and exclude keepers', async ({
  page,
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
  const admin = await send('/me'),
    player = await send('/me', 'GET', undefined, playerAuth.token)
  const stamp = Date.now()
  let match = await send('/matches', 'POST', {
    starts_at: '2097-10-30T20:30:00+03:00',
    location: `Сравнение ${stamp}`,
  })
  const guests = []
  for (const [label, position] of [
    ['Белый', 'field'],
    ['Чёрный', 'field'],
    ['Вратарь', 'keeper'],
  ]) {
    const guest = await send('/players/guests', 'POST', { alias: `${label} ${stamp}` })
    guests.push(guest)
    match = await send(`/matches/${match.id}/participants`, 'POST', {
      version: match.version,
      player_id: guest.id,
      position,
    })
  }
  match = await send(`/matches/${match.id}/actions/open`, 'POST', { version: match.version })
  match = await send(`/matches/${match.id}/join`, 'POST', { position: 'field' }, playerAuth.token)
  const registration = match.registrations.find(
    (r: { player_id: number }) => r.player_id === player.id,
  )
  match = await send(`/matches/${match.id}/registrations/${registration.id}/payment`, 'PUT', {
    version: match.version,
    paid: true,
  })
  async function vote(
    id: number,
    attack: number | null,
    defense: number,
    token: string,
    position = 'field',
  ) {
    const current = await send(`/players/${id}/ratings/${position}`, 'GET', undefined, token)
    await send(
      `/players/${id}/ratings`,
      'PUT',
      { position, attack, defense, revision: current.own?.revision ?? 0 },
      token,
    )
  }
  await vote(guests[0].id, 4, 2, adminAuth.token)
  await vote(guests[1].id, 2, 4, adminAuth.token)
  await vote(player.id, 0, 0, adminAuth.token)
  await vote(guests[0].id, 0, 0, playerAuth.token)
  await vote(guests[1].id, 2, 2, playerAuth.token)
  await vote(guests[2].id, null, 5, adminAuth.token, 'keeper')
  match = await send(`/matches/${match.id}/actions/finalize`, 'POST', { version: match.version })
  match = await send(`/matches/${match.id}/teams`, 'PUT', {
    version: match.version,
    assignments: Object.fromEntries(
      match.registrations.map((r: { id: number; player_id: number }) => [
        r.id,
        r.player_id === guests[1].id ? 'black' : 'white',
      ]),
    ),
  })
  const before = await send(`/matches/${match.id}`)
  await page.addInitScript(
    (token) => sessionStorage.setItem('fczhk-session', token),
    playerAuth.token,
  )
  await page.goto(`/?game=${match.id}&screen=lineup`)
  const comparison = page.getByRole('region', { name: 'Сравнение оценок составов', exact: true })
  const upper = comparison.getByRole('region', { name: 'Основные оценки', exact: true })
  const lower = comparison.getByRole('region', { name: 'Оценки для сравнения', exact: true })
  const values = (block: typeof upper) => block.locator('.lineup-rating-metrics b')
  await expect(values(upper)).toHaveText(['2', '1', '3', '2', '3', '5'])
  await expect(lower.locator('.lineup-rating-select')).toContainText(player.alias)
  await expect(values(lower)).toHaveText(['≥ 0', '≥ 0', '≥ 0', '2', '2', '4'])
  async function choose(block: typeof upper, alias?: string) {
    await block.getByRole('button', { name: /^Выбрать источник:/ }).click()
    if (alias) await block.getByRole('searchbox').fill(alias)
    await block
      .locator('.lineup-rating-options')
      .getByRole('button', { name: alias ? new RegExp(alias) : 'Общие оценки', exact: !alias })
      .click()
  }
  await upper.getByRole('button', { name: /^Выбрать источник:/ }).click()
  await expect(upper.locator('.lineup-rating-options')).toContainText(player.alias)
  await expect(upper.locator('.lineup-rating-options')).not.toContainText(admin.alias)
  await expect(upper.locator('.lineup-rating-options')).not.toContainText(guests[0].alias)
  await upper.getByRole('searchbox').press('Escape')
  await choose(lower, admin.alias)
  await expect(values(lower)).toHaveText(['4', '2', '6', '2', '4', '6'])
  await expect(values(upper)).toHaveText(['2', '1', '3', '2', '3', '5'])
  await expect(comparison.getByLabel('Разница: Белые').locator('b')).toHaveText(['−2', '−1', '−3'])
  await expect(comparison.getByLabel('Разница: Чёрные').locator('b')).toHaveText(['0', '−1', '−1'])
  await choose(upper, player.alias)
  await expect(values(lower)).toHaveText(['4', '2', '6', '2', '4', '6'])
  await expect(comparison.getByLabel('Разница: Белые').locator('b')).toHaveText(['—', '—', '—'])
  await choose(upper, admin.alias)
  await expect(comparison.getByLabel('Разница: Белые').locator('b')).toHaveText(['0', '0', '0'])
  await choose(lower)
  await expect(values(lower)).toHaveText(['2', '1', '3', '2', '3', '5'])
  await expect(comparison.getByLabel('Разница: Белые').locator('b')).toHaveText(['+2', '+1', '+3'])
  for (const width of [320, 500, 640, 768, 1024]) {
    await page.setViewportSize({ width, height: 1000 })
    await lower.getByRole('button', { name: /^Выбрать источник:/ }).click()
    await expect(lower.getByRole('searchbox')).toBeVisible()
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
    // Partial sums must fit their columns, not only the page as a whole.
    expect(
      await comparison.locator('.lineup-rating-metrics b').evaluateAll((elements) => {
        const canvas = document.createElement('canvas'),
          context = canvas.getContext('2d')!
        return elements.every((element) => {
          context.font = getComputedStyle(element).font
          return context.measureText('≥ 39,99').width <= element.clientWidth
        })
      }),
    ).toBe(true)
    await page.screenshot({
      path: `test-results/lineup-rating-comparison-${width}.png`,
      fullPage: true,
    })
    await lower.getByRole('searchbox').press('Escape')
  }
  await lower.getByText('Оценки по игрокам', { exact: true }).first().click()
  await expect(lower.locator('table').first()).toContainText(guests[0].alias)
  const after = await send(`/matches/${match.id}`)
  expect({ ...after, publications: publicationState(after) }).toEqual({
    ...before,
    publications: publicationState(before),
  })
})
