import { expect, test } from '@playwright/test'
import { defaultSeason } from '../src/seasons'

test('season filter follows statistics, player profile, archive and predictions', async ({
  page,
}) => {
  await page.clock.setFixedTime(new Date('2026-10-18T12:00:00Z'))
  const { token } = await (await page.request.post('/api/auth/demo/player')).json()
  const headers = { Authorization: `Bearer ${token}` }
  const people = await (await page.request.get('/api/players', { headers })).json()
  const person = people[0]
  const stats = await (
    await page.request.get(`/api/players/${person.id}/stats`, { headers })
  ).json()
  const boards = await (await page.request.get('/api/leaderboards', { headers })).json()
  const games = await (await page.request.get('/api/matches?limit=20', { headers })).json()
  const requests: string[] = []
  page.on('request', (request) => requests.push(request.url()))
  await page.addInitScript((token) => sessionStorage.setItem('fczhk-session', token), token)
  await page.route('**/api/seasons', (route) =>
    route.fulfill({ json: ['2027', '2026', '2024-2025'] }),
  )
  await page.route('**/api/leaderboards*', (route) => {
    const season = new URL(route.request().url()).searchParams.get('season')
    return route.fulfill({
      json: {
        ...boards,
        results: {
          matches: season === '2024-2025' ? 46 : season === '2026' ? 20 : 66,
          boards: boards.results.boards,
        },
      },
    })
  })
  await page.route(`**/api/players/${person.id}/stats*`, (route) => {
    const season = new URL(route.request().url()).searchParams.get('season')
    return route.fulfill({
      json: { ...stats, games: season === '2024-2025' ? 17 : season === '2026' ? 12 : 29 },
    })
  })
  await page.route('**/api/matches?*', (route) =>
    route.fulfill({ json: games.map((game: object) => ({ ...game, season: '2024-2025' })) }),
  )
  await page.goto('/')
  await page.getByRole('button', { name: 'Игроки', exact: true }).click()
  await expect(page.getByRole('combobox', { name: 'Период статистики', exact: true })).toHaveValue(
    '2026',
  )
  await expect(page.getByRole('heading', { name: 'Зачёты сезона 2026', exact: true })).toBeVisible()
  await expect(page.getByText('20 завершённых игр.', { exact: false })).toBeVisible()
  await expect
    .poll(() => requests.some((url) => url.endsWith('/api/game-ratings?season=2026')))
    .toBe(true)
  await page.getByRole('textbox', { name: 'Поиск игроков', exact: true }).fill(person.alias)
  await page
    .locator('.player-card')
    .filter({ has: page.getByRole('heading', { name: person.alias, exact: true }) })
    .getByRole('button', { name: 'Статистика', exact: true })
    .click()
  await expect(
    page.getByRole('dialog').getByRole('combobox', { name: 'Период статистики', exact: true }),
  ).toHaveValue('2026')
  await expect(
    page.getByRole('dialog').locator('.stats-grid').getByText('12', { exact: true }),
  ).toBeVisible()
  await page.keyboard.press('Escape')
  await page
    .getByRole('combobox', { name: 'Период статистики', exact: true })
    .selectOption('2024-2025')
  await expect(
    page.getByRole('heading', { name: 'Зачёты сезона 2024-2025', exact: true }),
  ).toBeVisible()
  await expect(page.getByText('46 завершённых игр.', { exact: false })).toBeVisible()
  await expect(
    page.getByRole('heading', { name: 'OpenSkill · сезон 2024-2025', exact: true }),
  ).toBeVisible()
  await expect
    .poll(() => requests.some((url) => url.endsWith('/api/game-ratings?season=2024-2025')))
    .toBe(true)
  await page.getByRole('textbox', { name: 'Поиск игроков', exact: true }).fill(person.alias)
  await page
    .locator('.player-card')
    .filter({ has: page.getByRole('heading', { name: person.alias, exact: true }) })
    .getByRole('button', { name: 'Статистика', exact: true })
    .click()
  const dialog = page.getByRole('dialog')
  await expect(
    dialog.getByRole('combobox', { name: 'Период статистики', exact: true }),
  ).toHaveValue('2024-2025')
  await expect(dialog.locator('.stats-grid').getByText('17', { exact: true })).toBeVisible()
  await dialog.getByRole('combobox', { name: 'Период статистики', exact: true }).selectOption('')
  await expect(dialog.locator('.stats-grid').getByText('29', { exact: true })).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(page.getByRole('combobox', { name: 'Период статистики', exact: true })).toHaveValue(
    '',
  )
  await expect(page.getByRole('heading', { name: 'Общие зачёты', exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Профиль', exact: true }).click()
  await expect(page.getByRole('combobox', { name: 'Период статистики', exact: true })).toHaveValue(
    '',
  )
  await page.getByRole('button', { name: 'Архив', exact: true }).click()
  await page
    .getByRole('combobox', { name: 'Период статистики', exact: true })
    .selectOption('2024-2025')
  await expect
    .poll(() => requests.some((url) => url.includes('/api/matches?limit=20&season=2024-2025')))
    .toBe(true)
  await expect(
    page.locator('.archive-card').first().getByText('Сезон 2024-2025', { exact: true }),
  ).toBeVisible()
  await page.getByRole('button', { name: 'Прогнозы', exact: true }).click()
  await expect(
    page.getByRole('heading', { name: 'Зачёт сезона 2024-2025', exact: true }),
  ).toBeVisible()
  await expect
    .poll(() => requests.some((url) => url.endsWith('/api/predictions/standings?season=2024-2025')))
    .toBe(true)
  await page.getByRole('button', { name: 'Профиль', exact: true }).click()
  await page.getByRole('combobox', { name: 'Период статистики', exact: true }).selectOption('')
  await page.getByRole('button', { name: 'Выйти из аккаунта', exact: true }).click()
  await page.getByRole('button', { name: 'Войти игроком', exact: true }).click()
  await page.getByRole('button', { name: 'Игроки', exact: true }).click()
  await expect(page.getByRole('combobox', { name: 'Период статистики', exact: true })).toHaveValue(
    '2026',
  )
})

test('default season uses the Moscow year and falls back to the latest available season', () => {
  expect(defaultSeason(['2027', '2026', '2024-2025'], new Date('2026-10-18T12:00:00Z'))).toBe(
    '2026',
  )
  expect(defaultSeason(['2027', '2026'], new Date('2026-12-31T21:30:00Z'))).toBe('2027')
  expect(defaultSeason(['2024-2025', '2023'], new Date('2026-10-18T12:00:00Z'))).toBe('2024-2025')
  expect(defaultSeason([], new Date('2026-10-18T12:00:00Z'))).toBe('')
})
