import { test, expect } from './app-test'
import { answerConfirmation } from './confirmation-helpers'

test('an empty rating day creates a gap, while a later real zero remains visible', async ({
  page,
  request,
}) => {
  const auth = await (await request.post('/api/auth/demo/admin')).json()
  const headers = { Authorization: `Bearer ${auth.token}` }
  const guest = await (
    await request.post('/api/players/guests', {
      headers,
      data: { alias: `График удаления ${Date.now()}` },
    })
  ).json()
  const today = new Date().toISOString().slice(0, 10)
  const day = (n: number) =>
    new Date(Date.parse(`${today}T12:00:00Z`) - n * 86400000).toISOString().slice(0, 10)
  await page.route(`**/api/players/${guest.id}/rating-history`, (route) =>
    route.fulfill({
      json: {
        as_of: `${today}T12:00:00Z`,
        timezone: 'Europe/Moscow',
        method: 'trimmed_mean_20_percent',
        keeper: [],
        field: [
          { date: day(2), at: `${day(2)}T12:00:00Z`, attack: 4, defense: 3, count: 1, changes: 1 },
          {
            date: day(1),
            at: `${day(1)}T12:00:00Z`,
            attack: null,
            defense: null,
            count: 0,
            changes: 1,
          },
          { date: today, at: `${today}T12:00:00Z`, attack: 0, defense: 0, count: 1, changes: 1 },
        ],
      },
    }),
  )
  await page.addInitScript((token) => sessionStorage.setItem('fczhk-session', token), auth.token)
  await page.goto('/')
  await page.getByRole('button', { name: 'Игроки', exact: true }).click()
  await page.getByLabel('Поиск игроков').fill(guest.alias)
  await page.locator('.catalog-person .player-name').click()
  const history = page.getByRole('region', { name: 'Динамика общих оценок' })
  await expect(history.locator('.rating-history-series.attack circle')).toHaveCount(2)
  expect(
    await history.locator('.rating-history-series.attack path').getAttribute('d'),
  ).not.toContain('C')
  await history.getByRole('button', { name: 'Предыдущая дата', exact: true }).click()
  await expect(history.locator('.rating-history-selection circle')).toHaveCount(0)
  await expect(history.locator('.rating-history-values b')).toHaveText(['—', '—'])
  await history.getByRole('button', { name: 'Следующая дата', exact: true }).click()
  await expect(history.locator('.rating-history-selection circle')).toHaveCount(2)
  await expect(history.locator('.rating-history-values b')).toHaveText(['0', '0'])
})

test('remove field and keeper votes, cancel, re-rate, preserve drafts on conflict and recover a lost response', async ({
  page,
  request,
}) => {
  const auth = await (await request.post('/api/auth/demo/admin')).json()
  const headers = { Authorization: `Bearer ${auth.token}` }
  const guest = await (
    await request.post('/api/players/guests', {
      headers,
      data: { alias: `Удаление ${Date.now()}` },
    })
  ).json()
  async function vote(position: string, revision: number, defense: number) {
    const response = await request.put(`/api/players/${guest.id}/ratings`, {
      headers,
      data: { position, revision, attack: position === 'field' ? 0 : null, defense },
    })
    expect(response.ok()).toBe(true)
  }
  const read = async (position: string) =>
    (await request.get(`/api/players/${guest.id}/ratings/${position}`, { headers })).json()
  await vote('field', 0, 3)
  await vote('keeper', 0, 4)
  await page.addInitScript((token) => sessionStorage.setItem('fczhk-session', token), auth.token)
  await page.goto('/')
  await page.getByRole('button', { name: 'Игроки', exact: true }).click()
  await page.getByLabel('Поиск игроков').fill(guest.alias)
  const remove = () =>
    page.getByRole('button', { name: `Удалить мою оценку: ${guest.alias}`, exact: true })
  await answerConfirmation(remove(), false, 'Удалить мою оценку')
  expect((await read('field')).own.revision).toBe(1)
  await answerConfirmation(remove(), true, 'полевой')
  await expect(page.getByLabel(`Моя атака: ${guest.alias}`, { exact: true })).toHaveValue('')
  await expect(page.getByRole('status').filter({ hasText: 'Оценка удалена:' })).toBeVisible()
  expect((await read('field')).own.withdrawn).toBe(true)
  expect((await read('keeper')).own.defense).toBe(4)
  await page.getByLabel(`Моя атака: ${guest.alias}`, { exact: true }).fill('2')
  await page.getByLabel(`Моя защита: ${guest.alias}`, { exact: true }).fill('1')
  const catalogRefresh = page.waitForResponse(
    (r) => r.url().endsWith('/api/players') && r.request().method() === 'GET',
  )
  await page.getByRole('button', { name: `Сохранить оценки: ${guest.alias}`, exact: true }).click()
  const refreshed = await catalogRefresh
  await refreshed.finished()
  const catalog = await refreshed.json()
  expect(catalog.find((p: { id: number }) => p.id === guest.id).my_ratings.field.revision).toBe(3)
  await expect(page.getByRole('status').filter({ hasText: 'Оценки сохранены:' })).toBeVisible()
  expect((await read('field')).own.revision).toBe(3)
  // An outside edit prevents deleting a version that has not been reviewed.
  await vote('field', 3, 5)
  await answerConfirmation(remove(), true, 'Удалить мою оценку')
  await expect(page.getByRole('alert')).toContainText('уже изменена')
  expect((await read('field')).own.revision).toBe(4)
  await page.reload()
  await page.getByRole('button', { name: 'Игроки', exact: true }).click()
  await page.getByLabel('Поиск игроков').fill(guest.alias)
  let writes = 0
  await page.route(`**/api/players/${guest.id}/ratings/field`, async (route) => {
    if (route.request().method() !== 'DELETE') return route.continue()
    writes++
    if (writes === 1) {
      await route.fetch()
      await route.abort('failed')
    } else await route.continue()
  })
  await answerConfirmation(remove(), true, 'Удалить мою оценку')
  await expect(page.getByRole('alert')).toContainText('Изменения могли сохраниться')
  await answerConfirmation(remove(), true, 'Удалить мою оценку')
  await expect(remove()).toHaveCount(0)
  expect((await read('field')).own.revision).toBe(5)
  await page.locator('.catalog-person .player-name').click()
  await page.getByRole('button', { name: 'Оценить игрока', exact: true }).click()
  const modal = page.getByRole('dialog')
  await modal.getByRole('button', { name: 'Вратарь', exact: true }).click()
  await answerConfirmation(
    modal.getByRole('button', { name: `Удалить мою оценку: ${guest.alias}`, exact: true }),
    true,
    'вратарь',
  )
  await expect(modal.getByRole('status').filter({ hasText: 'Ваша оценка удалена' })).toBeVisible()
  await expect(modal.getByLabel('Оценка защиты', { exact: true })).toHaveValue('')
  await expect(modal.getByRole('button', { name: 'Сохранить оценку', exact: true })).toBeEnabled()
  await modal.getByText(/Все оценки и история/).click()
  await expect(modal.getByText('Оценка удалена автором', { exact: true })).toBeVisible()
  await modal.getByText('История изменений', { exact: true }).click()
  await expect(modal.getByText(/#2.*Оценка удалена автором/)).toBeVisible()
  expect((await read('keeper')).own.withdrawn).toBe(true)
})
