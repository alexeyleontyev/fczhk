import { test, expect, type Page } from '@playwright/test'

async function login(page: Page, role = 'admin') {
  await page.goto('/')
  await page
    .getByRole('button', {
      name: role === 'admin' ? 'Войти администратором' : 'Войти игроком',
      exact: true,
    })
    .click()
  await expect(page.getByRole('heading', { name: 'Выходим на поле.' })).toBeVisible()
  const token = await page.evaluate(() => sessionStorage.getItem('fczhk-session'))
  return async (method: string, path: string, data?: unknown) => {
    const response = await page.request.fetch('/api' + path, {
      method,
      data,
      headers: { Authorization: `Bearer ${token}` },
    })
    expect(response.ok(), `${method} ${path}: ${await response.text()}`).toBeTruthy()
    return response.json()
  }
}

test('mobile player: own ratings, role separation, skip and privacy', async ({ page }) => {
  const api = await login(page, 'player')
  const people = await api('GET', '/players')
  const target = people.find((p: { alias: string }) => p.alias === 'Алексей')
  await page.getByRole('button', { name: 'Игроки', exact: true }).click()
  await page.getByLabel('Поиск игроков').fill('Алексей')
  await page.getByRole('button', { name: 'Оценки: Алексей', exact: true }).click()
  const modal = page.getByRole('dialog')
  await modal.getByRole('button', { name: 'Полевой', exact: true }).click()
  await expect(modal.getByLabel('Оценка атаки')).toBeVisible()
  await modal.getByLabel('Оценка атаки').fill('1,3')
  await modal.getByLabel('Оценка защиты').fill('2.2')
  await modal.getByRole('button', { name: 'Сохранить оценку', exact: true }).click()
  await expect(modal.getByRole('button', { name: 'Сохранить оценку', exact: true })).toBeEnabled()
  await modal.getByLabel('Оценка атаки').fill('4,6')
  await modal.getByLabel('Оценка защиты').fill('3.5')
  await modal.getByRole('button', { name: 'Сохранить оценку', exact: true }).click()
  await expect(modal.getByRole('button', { name: 'Сохранить оценку', exact: true })).toBeEnabled()
  await expect(modal.getByText(/Все оценки и история/)).toHaveCount(0)
  let own = await api('GET', `/players/${target.id}/ratings/field`)
  expect(own.own.attack).toBe(4.6)
  expect(own.reviews).toBeUndefined()
  expect(own.averages.count).toBeUndefined()
  await modal.getByRole('button', { name: 'Вратарь', exact: true }).click()
  await expect(modal.getByLabel('Оценка атаки')).toHaveCount(0)
  await expect(modal.getByLabel('Оценка защиты')).toBeVisible()
  await modal.getByLabel('Оценка защиты').fill('5')
  await modal.getByRole('button', { name: 'Сохранить оценку', exact: true }).click()
  await expect(modal.getByRole('button', { name: 'Сохранить оценку', exact: true })).toBeEnabled()
  expect((await api('GET', `/players/${target.id}/ratings/keeper`)).own.defense).toBe(5)
  await expect(modal.getByLabel('Оценка защиты')).toHaveValue('5')
  await page.screenshot({ path: 'test-results/mobile-rating.png', fullPage: true })
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  await modal.getByRole('button', { name: 'Закрыть', exact: true }).click()
  await page.getByRole('button', { name: 'Оценить игроков', exact: true }).click()
  await modal.getByLabel('Оцениваемый игрок').selectOption({ label: 'Алексей' })
  await modal.getByRole('button', { name: 'Полевой', exact: true }).click()
  await expect(modal.getByLabel('Оценка атаки')).toHaveValue('4.6')
  await modal.getByRole('button', { name: 'Пропустить', exact: true }).click()
  own = await api('GET', `/players/${target.id}/ratings/field`)
  expect(own.own.attack).toBe(4.6)
  const nextId = await modal.getByLabel('Оцениваемый игрок').inputValue()
  await modal.getByRole('button', { name: 'Закрыть', exact: true }).click()
  await page.reload()
  await page.getByRole('button', { name: 'Игроки', exact: true }).click()
  await page.getByRole('button', { name: 'Оценить игроков', exact: true }).click()
  await expect(modal.getByLabel('Оцениваемый игрок')).toHaveValue(nextId)
})

test('admin can see authors and rating history without self-rating', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1050 })
  const api = await login(page)
  const people = await api('GET', '/players')
  const target = people.find((p: { alias: string }) => p.alias === 'Алексей')
  const playerLogin = await page.request.post('/api/auth/demo/player')
  const headers = { Authorization: `Bearer ${(await playerLogin.json()).token}` }
  let current = await (
    await page.request.get(`/api/players/${target.id}/ratings/field`, { headers })
  ).json()
  for (const attack of [1.3, 4.6]) {
    const response = await page.request.put(`/api/players/${target.id}/ratings`, {
      headers,
      data: { position: 'field', attack, defense: 3.5, revision: current.own?.revision ?? 0 },
    })
    expect(response.ok()).toBeTruthy()
    current = await response.json()
  }
  await page.getByRole('button', { name: 'Игроки', exact: true }).click()
  await page.getByLabel('Поиск игроков').fill('Алексей')
  await page.getByRole('button', { name: 'Оценки: Алексей', exact: true }).click()
  const modal = page.getByRole('dialog')
  await expect(modal.getByText('Вы можете посмотреть оценки, но не оценивать себя.')).toBeVisible()
  await expect(modal.getByLabel('Оценка атаки')).toHaveCount(0)
  await modal.getByText(/Все оценки и история/).click()
  await expect(modal.locator('strong').filter({ hasText: /^Михаил$/ })).toBeVisible()
  await modal.getByText('История изменений', { exact: true }).click()
  await expect(modal.getByText(/А 4,6 · З 3,5/).last()).toBeVisible()
  await page.screenshot({ path: 'test-results/desktop-rating-history.png', fullPage: true })
})

test('player can rate a catalog card without Telegram from its card and full rating list', async ({
  page,
}) => {
  const api = await login(page, 'player')
  const admin = await (await page.request.post('/api/auth/demo/admin')).json()
  const alias = `Каталог без Telegram ${Date.now()}`
  const response = await page.request.post('/api/players/guests', {
    headers: { Authorization: `Bearer ${admin.token}` },
    data: { alias },
  })
  expect(response.status()).toBe(201)
  const guest = await response.json()
  await page.reload()
  await page.getByRole('button', { name: 'Игроки', exact: true }).click()
  await page.getByLabel('Поиск игроков').fill(alias)
  await page.getByRole('button', { name: `Оценки: ${alias}`, exact: true }).click()
  const modal = page.getByRole('dialog')
  await modal.getByRole('button', { name: 'Полевой', exact: true }).click()
  await modal.getByLabel('Оценка атаки').fill('2,7')
  await modal.getByLabel('Оценка защиты').fill('4,1')
  await modal.getByRole('button', { name: 'Сохранить оценку', exact: true }).click()
  await expect(modal.getByRole('button', { name: 'Сохранить оценку', exact: true })).toBeEnabled()
  expect((await api('GET', `/players/${guest.id}/ratings/field`)).own.attack).toBe(2.7)
  await modal.getByRole('button', { name: 'Закрыть', exact: true }).click()
  await page.getByRole('button', { name: 'Оценить игроков', exact: true }).click()
  await modal.getByLabel('Оцениваемый игрок').selectOption(String(guest.id))
  await expect(modal.getByLabel('Оценка атаки')).toHaveValue('2.7')
  await expect(modal.getByText(/Все оценки и история/)).toHaveCount(0)
})

test('mobile: temporary guest rating, 3 distinct teams, keepers, manual editing and frozen approval', async ({
  page,
}) => {
  const api = await login(page)
  const day = new Date(Date.now() + (12000 + Math.floor(Math.random() * 4000)) * 86400000)
    .toISOString()
    .slice(0, 10)
  let m = await api('POST', '/matches', {
    starts_at: `${day}T20:00:00+03:00`,
    location: 'Демо MVP 2 · автоподбор',
    cost: 80000,
  })
  m = await api('POST', `/matches/${m.id}/actions/open`, { version: m.version })
  let firstGuestId = 0
  let communityGuestId = 0
  for (let i = 0; i < 18; i++) {
    const alias = i < 16 ? `Баланс ${String(i + 1).padStart(2, '0')}` : `Вратарь ${i - 15}`
    const guest = await api('POST', '/players/guests', { alias })
    if (i === 0) firstGuestId = guest.id
    if (i === 1) communityGuestId = guest.id
    const position = i < 16 ? 'field' : 'keeper'
    m = await api('POST', `/matches/${m.id}/participants`, {
      version: m.version,
      player_id: guest.id,
      position,
    })
    if (i === 1 || i === 15) continue // Community-only player; last rating filled from the phone UI.
    const reg = m.registrations.find((r: { player_id: number }) => r.player_id === guest.id)
    m = await api('PUT', `/matches/${m.id}/registrations/${reg.id}/rating`, {
      version: m.version,
      position,
      attack: i < 16 ? 2 + (i % 6) * 0.4 : null,
      defense: i < 16 ? 2 + (i % 4) * 0.5 : i === 16 ? 0 : 5,
    })
  }
  await api('PUT', `/players/${firstGuestId}/ratings`, {
    position: 'field',
    attack: 4.5,
    defense: 1.2,
    revision: 0,
  })
  await api('PUT', `/players/${communityGuestId}/ratings`, {
    position: 'field',
    attack: 2.4,
    defense: 2.5,
    revision: 0,
  })
  await page.goto(`/?game=${m.id}`)
  await page.getByRole('button', { name: 'Финализировать сбор', exact: true }).click()
  await page
    .getByRole('dialog')
    .getByRole('button', { name: 'Финализировать сбор', exact: true })
    .click()
  await expect(
    page.getByRole('button', { name: 'Рассчитать варианты', exact: true }),
  ).toBeDisabled()
  await page.getByText(/Рейтинги на эту игру ·/).click()
  await page.getByRole('button', { name: 'Рейтинг на игру: Баланс 16', exact: true }).click()
  const form = page.getByRole('form', { name: 'Временный рейтинг: Баланс 16' })
  await form.getByLabel('Оценка атаки').fill('4,2')
  await form.getByLabel('Оценка защиты').fill('3.4')
  await form.getByRole('button', { name: 'Сохранить на игру', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Рассчитать варианты', exact: true })).toBeEnabled()
  await expect(page.locator('.collection-strength')).toContainText('Сила сбора:')
  await expect(page.locator('.collection-strength')).toContainText('Оценены 18 из 18 игроков')
  await page.getByRole('button', { name: 'Рассчитать варианты', exact: true }).click()
  await expect(page.getByRole('article', { name: 'Вариант 3', exact: true })).toBeVisible()
  const runs = await api('GET', `/matches/${m.id}/balance`)
  const firstVariant = page.getByRole('article', { name: 'Вариант 1', exact: true })
  const firstPlayer = firstVariant.locator('.variant-player').filter({ hasText: 'Баланс 01' })
  await expect(firstPlayer.locator('small')).toHaveText('А 2 · З 2 · на игру')
  const communityPlayer = firstVariant.locator('.variant-player').filter({ hasText: 'Баланс 02' })
  await expect(communityPlayer.locator('small')).toHaveText('А 2,4 · З 2,5')
  await expect(communityPlayer.getByText(/на игру/)).toHaveCount(0)
  await expect(firstVariant.getByText(/нет оценок|оценка не задана|Сообщество:/)).toHaveCount(0)
  expect(runs[0].result.partition_count).toBe(6435)
  for (let i = 0; i < 3; i++)
    for (let j = i + 1; j < 3; j++) expect(runs[0].result.distances[i][j]).toBeGreaterThanOrEqual(6)
  await page.getByText(/Рейтинги на эту игру ·/).click()
  await page.locator('.auto-teams').screenshot({ path: 'test-results/mobile-balance.png' })
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  await page.getByRole('button', { name: 'Выбрать вариант 1', exact: true }).click()
  await expect(page.getByLabel('Команда: Вратарь 1', { exact: true })).toHaveValue('')
  await page.getByLabel('Команда: Вратарь 1', { exact: true }).selectOption('white')
  await expect(page.getByLabel('Команда: Вратарь 2', { exact: true })).toBeEnabled()
  await page.getByLabel('Команда: Вратарь 2', { exact: true }).selectOption('black')
  await expect(page.getByRole('button', { name: 'Утвердить команды', exact: true })).toBeEnabled()
  m = await api('GET', `/matches/${m.id}`)
  const w = m.registrations.find(
    (r: { position: string; team: string }) => r.position === 'field' && r.team === 'white',
  )
  const b = m.registrations.find(
    (r: { position: string; team: string }) => r.position === 'field' && r.team === 'black',
  )
  await page.getByLabel(`Команда: ${w.alias}`, { exact: true }).selectOption('black')
  await expect(page.getByLabel(`Команда: ${b.alias}`, { exact: true })).toBeEnabled()
  await page.getByLabel(`Команда: ${b.alias}`, { exact: true }).selectOption('white')
  await expect(page.getByRole('button', { name: 'Утвердить команды', exact: true })).toBeEnabled()
  m = await api('GET', `/matches/${m.id}`)
  expect(m.team_ratings.method).toBe('auto-edited')
  await page.getByRole('button', { name: 'Утвердить команды', exact: true }).click()
  await expect(page.getByText('Команды готовы', { exact: true })).toBeVisible()
  await page.reload()
  await expect(page.getByText('Команды готовы', { exact: true })).toBeVisible()
  await page.screenshot({ path: 'test-results/mobile-mvp2-approved.png', fullPage: true })
  m = await api('GET', `/matches/${m.id}`)
  expect(m.team_ratings.frozen).toBe(true)
  await expect(page.locator('.collection-strength')).toContainText('Зафиксировано при утверждении')
  await expect(page.locator('.team-grid').getByText(/Сила команды:/)).toHaveCount(2)
  await page.getByRole('button', { name: 'Распределить вручную с нуля', exact: true }).click()
  await page.getByRole('button', { name: 'Начать вручную', exact: true }).click()
  await expect(page.getByText('Сбор завершен', { exact: true })).toBeVisible()
  await expect(page.getByLabel('Команда: Вратарь 1', { exact: true })).toHaveValue('')
})
