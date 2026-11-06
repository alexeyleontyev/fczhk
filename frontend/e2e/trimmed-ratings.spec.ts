import { test, expect } from '@playwright/test'

test('community rule and per-score inclusion are visible in catalog, profiles and leaderboards', async ({
  page,
  request,
}) => {
  const auth = await (await request.post('/api/auth/demo/admin')).json()
  const headers = { Authorization: `Bearer ${auth.token}` }
  const alias = `Усечённые оценки ${Date.now()}`
  const guest = await (
    await request.post('/api/players/guests', { headers, data: { alias } })
  ).json()
  await request.put(`/api/players/${guest.id}/ratings`, {
    headers,
    data: { position: 'field', attack: 1, defense: 5, revision: 0 },
  })
  await page.addInitScript((token) => sessionStorage.setItem('fczhk-session', token), auth.token)
  await page.goto('/')
  await page.getByRole('button', { name: 'Игроки', exact: true }).click()
  const catalog = page.locator('.catalog-table-panel')
  await catalog.getByText('Как считаются общие оценки', { exact: true }).click()
  await expect(catalog).toContainText('Усечённое среднее'.toLocaleLowerCase('ru'))
  await expect(catalog).toContainText('из 13 оценок остаются 9')
  await page.getByLabel('Поиск игроков', { exact: true }).fill(alias)
  await page.locator('.catalog-person').getByRole('button', { name: alias, exact: true }).click()
  const profile = page.getByRole('dialog', { name: 'Профиль игрока', exact: true })
  await profile.getByText('Как считаются общие оценки', { exact: true }).click()
  await expect(profile).toContainText('При 1–4 оценках считаем обычное среднее')
  await profile.getByText('Как оценили другие игроки', { exact: true }).click()
  await expect(profile.locator('.review-score.included')).toHaveCount(2)
  await expect(profile.getByLabel('Атака 1: учтена', { exact: true })).toBeVisible()

  // The profile keeps original scores visible and displays each characteristic's
  // independent retained weight, including fair ties at the trimming boundary.
  await page.route(`**/api/players/${guest.id}/reviews`, (route) =>
    route.fulfill({
      json: {
        field: [
          {
            author_id: 801,
            author: 'Крайняя атака',
            attack: 5,
            defense: 3,
            attack_weight: 0,
            defense_weight: 1,
          },
          {
            author_id: 802,
            author: 'Равные оценки',
            attack: 1,
            defense: 0,
            attack_weight: 0.75,
            defense_weight: 0,
          },
        ],
        keeper: [
          {
            author_id: 803,
            author: 'Оценка вратаря',
            attack: null,
            defense: 5,
            attack_weight: null,
            defense_weight: 1,
          },
        ],
      },
    }),
  )
  await profile.getByRole('button', { name: 'Закрыть', exact: true }).click()
  await page.locator('.catalog-person').getByRole('button', { name: alias, exact: true }).click()
  await profile.getByText('Как оценили другие игроки', { exact: true }).click()
  await expect(
    profile.getByLabel('Атака 5: не участвует в среднем по правилу усечения', { exact: true }),
  ).toBeVisible()
  await expect(profile.getByLabel('Защита 3: учтена', { exact: true })).toBeVisible()
  await expect(profile.getByLabel('Атака 1: частично: 75%', { exact: true })).toBeVisible()
  await expect(
    profile.getByLabel('Защита 0: не участвует в среднем по правилу усечения', { exact: true }),
  ).toBeVisible()
  await expect(profile.getByLabel('Защита 5: учтена', { exact: true })).toBeVisible()
  for (const width of [320, 390, 1440]) {
    await page.setViewportSize({ width, height: 1000 })
    await profile.locator('.profile-reviews').scrollIntoViewIfNeeded()
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
    const reviews = profile.locator('.profile-reviews')
    for (const row of await reviews.locator('.profile-review').all()) {
      expect(await row.evaluate((el) => el.scrollWidth <= el.clientWidth)).toBe(true)
    }
    await page.screenshot({
      path: `test-results/trimmed-review-inclusion-${width}.png`,
      fullPage: true,
    })
  }
  await profile.getByRole('button', { name: 'Закрыть', exact: true }).click()
  await page.getByRole('tab', { name: 'Рейтинги', exact: true }).click()
  const community = page.locator('.leaderboard-board')
  await community.getByText('Как считаются общие оценки', { exact: true }).click()
  await expect(community).toContainText('усечённое среднее')
})
