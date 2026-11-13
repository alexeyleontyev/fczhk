import { test, expect } from './app-test'

test('a real saved vote appears below averages, keeps zero and refreshes after an edit', async ({
  page,
  request,
}) => {
  const auth = await (await request.post('/api/auth/demo/admin')).json()
  const headers = { Authorization: `Bearer ${auth.token}` }
  const alias = `История графика ${Date.now()}`
  const guest = await (
    await request.post('/api/players/guests', { headers, data: { alias } })
  ).json()
  expect(
    (
      await request.put(`/api/players/${guest.id}/ratings`, {
        headers,
        data: { position: 'field', attack: 0, defense: 4, revision: 0 },
      })
    ).ok(),
  ).toBe(true)
  const history = await (
    await request.get(`/api/players/${guest.id}/rating-history`, { headers })
  ).json()
  expect(history.field).toHaveLength(1)
  expect(history.field[0].attack).toBe(0)
  await page.addInitScript((token) => sessionStorage.setItem('fczhk-session', token), auth.token)
  await page.goto('/')
  await page.getByRole('button', { name: 'Игроки', exact: true }).click()
  await page.getByLabel('Поиск игроков', { exact: true }).fill(alias)
  await page.locator('.catalog-person').getByRole('button', { name: alias, exact: true }).click()
  const profile = page.getByRole('dialog', { name: 'Профиль игрока', exact: true })
  const graph = profile.getByRole('region', { name: 'Динамика общих оценок', exact: true })
  await expect(graph.locator('.rating-history-values b').first()).toHaveText('0')
  await expect(graph.locator('.rating-history-date')).toContainText('Оценщиков: 1')
  expect(
    await graph.evaluate((el) =>
      Boolean(el.previousElementSibling?.classList.contains('rating-averages')),
    ),
  ).toBe(true)
  await profile.getByRole('button', { name: 'Оценить игрока', exact: true }).click()
  const editor = page.getByRole('dialog', { name: 'Оценки игроков', exact: true })
  await editor.getByLabel('Оценка атаки').fill('2.4')
  await editor.getByLabel('Оценка защиты').fill('3.6')
  await editor.getByRole('button', { name: 'Сохранить оценку', exact: true }).click()
  await expect(editor.getByRole('button', { name: 'Сохранить оценку', exact: true })).toBeEnabled()
  await editor.getByRole('button', { name: 'Закрыть', exact: true }).click()
  await expect(graph.locator('.rating-history-values b').first()).toHaveText('2,4')
  await expect(graph.locator('.rating-history-date')).toContainText('записей за день: 2')
  for (const width of [320, 390, 1440]) {
    await page.setViewportSize({ width, height: 1000 })
    await graph.scrollIntoViewIfNeeded()
    await expect
      .poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth))
      .toBe(true)
    expect(await graph.evaluate((el) => el.scrollWidth <= el.clientWidth)).toBe(true)
    await page.screenshot({
      path: `test-results/profile-rating-history-${width}.png`,
      fullPage: true,
    })
  }
})

test('own profile supports daily dates, keyboard, keeper grades and dense histories', async ({
  page,
  request,
}) => {
  const auth = await (await request.post('/api/auth/demo/player')).json()
  const as_of = '2026-11-06T18:10:00Z'
  const base = { as_of, timezone: 'Europe/Moscow', method: 'trimmed_mean_20_percent' }
  const point = (date: string, attack: number | null, defense: number) => ({
    date,
    at: `${date}T10:00:00Z`,
    attack,
    defense,
  })
  let data = {
    ...base,
    field: [
      point('2026-10-18', 1.6875, 3.4375),
      point('2026-10-26', 1.77778, 3.44444),
      point('2026-11-05', 2.05556, 3.38889),
      point('2026-11-06', 1.88889, 3.38889),
    ],
    keeper: [point('2026-11-06', null, 0)],
  }
  await page.route(`**/api/players/${auth.player.id}/rating-history`, (route) =>
    route.fulfill({ json: data }),
  )
  await page.addInitScript((token) => sessionStorage.setItem('fczhk-session', token), auth.token)
  await page.goto('/')
  await page.getByRole('button', { name: 'Профиль', exact: true }).click()
  const graph = page.getByRole('region', { name: 'Динамика общих оценок', exact: true })
  await expect(graph.locator('.rating-history-values b').first()).toHaveText('1,89')
  await expect(graph).not.toContainText('Оценщиков:')
  const chart = graph.getByRole('button', { name: 'График средних оценок:', exact: false })
  await chart.focus()
  await page.keyboard.press('Home')
  await expect(graph.locator('.rating-history-date strong')).toHaveText('18 октября 2026')
  await expect(graph.locator('.rating-history-values b').first()).toHaveText('1,69')
  await page.keyboard.press('ArrowRight')
  await expect(graph.locator('.rating-history-date strong')).toHaveText('26 октября 2026')
  await graph.getByRole('button', { name: '7 дней', exact: true }).click()
  await expect(graph.locator('.rating-history-series circle')).toHaveCount(4)
  await graph.getByRole('button', { name: 'Предыдущая дата', exact: true }).click()
  await expect(graph.locator('.rating-history-date strong')).toHaveText('5 ноября 2026')
  await graph.getByRole('button', { name: 'Вратарь', exact: true }).click()
  await expect(graph.locator('.rating-history-values b')).toHaveCount(1)
  await expect(graph.locator('.rating-history-values b')).toHaveText('0')
  await expect(graph.locator('.rating-history-series.attack')).toHaveCount(0)

  data = {
    ...base,
    field: Array.from({ length: 365 }, (_, i) =>
      point(
        new Date(Date.parse('2025-11-07T00:00:00Z') + i * 86400000).toISOString().slice(0, 10),
        2 + Math.sin(i) / 10,
        3,
      ),
    ),
    keeper: [],
  }
  await page.reload()
  await page.getByRole('button', { name: 'Профиль', exact: true }).click()
  await expect(graph.locator('.rating-history-series path')).toHaveCount(2)
  await expect(graph.locator('.rating-history-series circle')).toHaveCount(0)
  await chart.focus()
  await page.keyboard.press('Home')
  await expect(graph.locator('.rating-history-date strong')).toHaveText('7 ноября 2025')
  await page.keyboard.press('End')
  await expect(graph.locator('.rating-history-date strong')).toHaveText('6 ноября 2026')
  await graph.getByRole('button', { name: '7 дней', exact: true }).click()
  await expect(graph.locator('.rating-history-series circle')).toHaveCount(14)
  for (const path of await graph.locator('.rating-history-series path').all())
    expect(await path.getAttribute('d')).not.toMatch(/NaN|Infinity/)
})

test('history failures can be retried; empty and unchanged keeper histories stay clear', async ({
  page,
  request,
}) => {
  const auth = await (await request.post('/api/auth/demo/player')).json()
  let fail = true
  let data: object = {
    as_of: '2026-11-06T18:10:00Z',
    timezone: 'Europe/Moscow',
    method: 'trimmed_mean_20_percent',
    field: [],
    keeper: [],
  }
  await page.route(`**/api/players/${auth.player.id}/rating-history`, (route) =>
    fail
      ? route.fulfill({ status: 503, json: { detail: 'История временно недоступна' } })
      : route.fulfill({ json: data }),
  )
  await page.addInitScript((token) => sessionStorage.setItem('fczhk-session', token), auth.token)
  await page.goto('/')
  await page.getByRole('button', { name: 'Профиль', exact: true }).click()
  const graph = page.getByRole('region', { name: 'Динамика общих оценок', exact: true })
  await expect(graph.getByRole('alert')).toContainText('История временно недоступна')
  fail = false
  await graph.getByRole('button', { name: 'Повторить', exact: true }).click()
  await expect(graph).toContainText('График появится после первой оценки')
  data = {
    as_of: '2026-11-06T18:10:00Z',
    timezone: 'Europe/Moscow',
    method: 'trimmed_mean_20_percent',
    field: [],
    keeper: [{ date: '2026-10-26', at: '2026-10-26T10:00:00Z', attack: null, defense: 0 }],
  }
  await page.reload()
  await page.getByRole('button', { name: 'Профиль', exact: true }).click()
  await expect(graph.locator('.rating-history-values b')).toHaveText('0')
  await expect(
    graph.getByRole('group', { name: 'Амплуа в истории оценок', exact: true }),
  ).toHaveCount(0)
  await graph.getByRole('button', { name: '7 дней', exact: true }).click()
  await expect(graph).toContainText('За 7 дней оценок не меняли')
  await expect(graph).toContainText('Последняя запись: 26 октября 2026')
  await expect(graph.getByRole('button', { name: 'Предыдущая дата', exact: true })).toBeDisabled()
  await expect(graph.locator('.rating-history-selection')).toHaveCount(0)
  for (const path of await graph.locator('.rating-history-series path').all())
    expect(await path.getAttribute('d')).not.toMatch(/NaN|Infinity/)
})
