import { expect, test, type APIRequestContext, type Page } from './app-test'

async function setup(page: Page, request: APIRequestContext, role = 'admin') {
  const auth = await (await request.post(`/api/auth/demo/${role}`)).json()
  const headers = { Authorization: `Bearer ${auth.token}` }
  async function send(path: string, method = 'GET', data?: object) {
    const result = await request.fetch(`/api${path}`, { method, data, headers })
    expect(result.ok(), await result.text()).toBe(true)
    return result.json()
  }
  await page.addInitScript((token) => sessionStorage.setItem('fczhk-session', token), auth.token)
  return { send, auth, headers }
}

test('rating drafts survive search, sections, modal closure, reload and bulk saving hidden rows', async ({
  page,
  request,
}) => {
  const { send } = await setup(page, request)
  const first = await send('/players/guests', 'POST', { alias: `Черновик первый ${Date.now()}` })
  const second = await send('/players/guests', 'POST', { alias: `Черновик второй ${Date.now()}` })
  await page.goto('/')
  await page.getByRole('button', { name: 'Игроки', exact: true }).click()
  const search = page.getByLabel('Поиск игроков')
  await search.fill(first.alias)
  await page.getByLabel(`Моя атака: ${first.alias}`, { exact: true }).fill('0')
  await page.getByLabel(`Моя защита: ${first.alias}`, { exact: true }).fill('3,7')
  await search.fill(second.alias)
  await page.getByLabel(`Моя атака: ${second.alias}`, { exact: true }).fill('4,2')
  await page.getByLabel(`Моя защита: ${second.alias}`, { exact: true }).fill('2,1')
  await page.getByRole('tab', { name: 'Рейтинги', exact: true }).click()
  await page.getByRole('tab', { name: 'Каталог', exact: true }).click()
  await search.fill(first.alias)
  await expect(page.getByLabel(`Моя защита: ${first.alias}`, { exact: true })).toHaveValue('3,7')
  await page.locator('.catalog-person .player-name').click()
  await page.getByRole('button', { name: 'Оценить игрока', exact: true }).click()
  await expect(page.getByLabel('Оценка атаки', { exact: true })).toHaveValue('0')
  await page.getByLabel('Оценка защиты', { exact: true }).fill('4,1')
  await page.getByRole('button', { name: 'Закрыть', exact: true }).click()
  await page.getByRole('button', { name: 'Оценить игрока', exact: true }).click()
  await expect(page.getByLabel('Оценка защиты', { exact: true })).toHaveValue('4,1')
  await page.reload()
  await page.getByRole('button', { name: 'Игроки', exact: true }).click()
  await search.fill(second.alias)
  await expect(page.getByRole('region', { name: 'Черновики оценок' })).toContainText(
    'Есть несохранённые изменения: 2',
  )
  await page.getByRole('button', { name: 'Сохранить все', exact: true }).click()
  await expect(page.getByRole('region', { name: 'Черновики оценок' })).toContainText(
    'Сохранено оценок: 2 из 2',
  )
  expect((await send(`/players/${first.id}/ratings/field`)).own).toMatchObject({
    attack: 0,
    defense: 4.1,
    revision: 1,
  })
  expect((await send(`/players/${second.id}/ratings/field`)).own).toMatchObject({
    attack: 4.2,
    defense: 2.1,
    revision: 1,
  })
  await search.fill(first.alias)
  await expect(page.getByLabel(`Моя защита: ${first.alias}`, { exact: true })).toHaveValue('4,1')
})

test('live match updates from another client preserve form input and recover from offline', async ({
  page,
  request,
  context,
}) => {
  const { send } = await setup(page, request)
  let match = await send('/matches', 'POST', {
    starts_at: '2097-06-01T20:00:00+03:00',
    location: 'Первый манеж',
  })
  match = await send(`/matches/${match.id}/actions/open`, 'POST', { version: match.version })
  await page.clock.install()
  await page.goto(`/?game=${match.id}`)
  await page.getByRole('button', { name: 'Изменить параметры', exact: true }).click()
  await page.getByLabel('Место игры', { exact: true }).fill('Мой несохранённый манеж')
  match = await send(`/matches/${match.id}`, 'PUT', {
    version: match.version,
    starts_at: match.starts_at,
    location: 'Другой клиент изменил место',
  })
  await page.clock.runFor(15100)
  await expect(page.locator('.match-hero')).toContainText('Другой клиент изменил место')
  await expect(page.getByLabel('Место игры', { exact: true })).toHaveValue(
    'Мой несохранённый манеж',
  )
  await page.getByRole('button', { name: 'Закрыть', exact: true }).click()
  await context.setOffline(true)
  await expect(page.getByLabel('Состояние обновления игры')).toContainText('Нет подключения')
  await context.setOffline(false)
  await expect(page.getByLabel('Состояние обновления игры')).toContainText('Обновлено')
  await page.getByRole('button', { name: 'Игроки', exact: true }).click()
  await page.getByRole('button', { name: 'Назад', exact: true }).click()
  await expect(page.locator('.match-hero')).toContainText('Другой клиент изменил место')
})

test('lost write response retains the draft and reconciliation prevents a duplicate revision', async ({
  page,
  request,
}) => {
  const { send } = await setup(page, request)
  const player = await send('/players/guests', 'POST', { alias: `Потерянный ответ ${Date.now()}` })
  await page.goto('/')
  await page.getByRole('button', { name: 'Игроки', exact: true }).click()
  await page.getByLabel('Поиск игроков').fill(player.alias)
  await page.getByLabel(`Моя атака: ${player.alias}`).fill('2,2')
  await page.getByLabel(`Моя защита: ${player.alias}`).fill('4,4')
  let writes = 0
  await page.route(`**/api/players/${player.id}/ratings`, async (route) => {
    writes++
    await route.fetch() // The server commits but the browser never receives confirmation.
    await route.abort('failed')
  })
  const save = page.getByRole('button', { name: `Сохранить оценки: ${player.alias}`, exact: true })
  await save.click()
  await expect(page.getByRole('alert')).toContainText('Изменения могли сохраниться')
  await expect(page.getByLabel(`Моя атака: ${player.alias}`)).toHaveValue('2,2')
  expect(writes).toBe(1)
  await save.click()
  await expect(save).toBeDisabled()
  await expect(page.getByRole('status').filter({ hasText: 'Оценки сохранены:' })).toBeVisible()
  expect(writes).toBe(1)
  expect((await send(`/players/${player.id}/ratings/field`)).own.revision).toBe(1)
})

test('request deadlines release controls; safe reads retry once and writes do not retry', async ({
  page,
  request,
}) => {
  const { send } = await setup(page, request)
  const player = await send('/players/guests', 'POST', { alias: `Таймаут ${Date.now()}` })
  await page.clock.install()
  await page.goto('/')
  await page.getByRole('button', { name: 'Игроки', exact: true }).click()
  await page.getByLabel('Поиск игроков').fill(player.alias)
  await page.getByLabel(`Моя атака: ${player.alias}`).fill('2')
  await page.getByLabel(`Моя защита: ${player.alias}`).fill('3')
  let reads = 0,
    writes = 0
  await page.route(`**/api/players/${player.id}/ratings/field`, () => {
    reads++
  })
  const save = page.getByRole('button', { name: `Сохранить оценки: ${player.alias}`, exact: true })
  await save.click()
  await expect.poll(() => reads).toBe(1)
  await page.clock.runFor(10500)
  await expect.poll(() => reads).toBe(2)
  await page.clock.runFor(10100)
  await expect(page.getByRole('alert')).toContainText('Сервер не ответил вовремя')
  await expect(save).toBeEnabled()
  await page.unroute(`**/api/players/${player.id}/ratings/field`)
  await page.route(`**/api/players/${player.id}/ratings`, () => {
    writes++
  })
  await save.click()
  await expect.poll(() => writes).toBe(1)
  await page.clock.runFor(15100)
  await expect(page.getByRole('alert')).toContainText('Изменения могли сохраниться')
  await expect(save).toBeEnabled()
  expect(writes).toBe(1)
  await expect(page.getByLabel(`Моя защита: ${player.alias}`)).toHaveValue('3')
})

test('bulk save keeps invalid drafts, separates accounts and requires accepting conflicting votes', async ({
  page,
  request,
}) => {
  const { send, headers } = await setup(page, request)
  const one = await send('/players/guests', 'POST', { alias: `Пакет верный ${Date.now()}` })
  const two = await send('/players/guests', 'POST', { alias: `Пакет неполный ${Date.now()}` })
  await page.goto('/')
  await page.getByRole('button', { name: 'Игроки', exact: true }).click()
  const search = page.getByLabel('Поиск игроков')
  await search.fill(one.alias)
  await page.getByLabel(`Моя атака: ${one.alias}`).fill('2')
  await page.getByLabel(`Моя защита: ${one.alias}`).fill('4')
  await search.fill(two.alias)
  await page.getByLabel(`Моя защита: ${two.alias}`).fill('3')
  await page.getByRole('button', { name: 'Сохранить все', exact: true }).click()
  await expect(page.getByRole('region', { name: 'Черновики оценок' })).toContainText(
    'Сохранено оценок: 1 из 2',
  )
  expect((await send(`/players/${one.id}/ratings/field`)).own.revision).toBe(1)
  expect((await send(`/players/${two.id}/ratings/field`)).own).toBeNull()
  await page.getByRole('button', { name: 'Сменить роль', exact: true }).click()
  await page.getByRole('button', { name: 'Войти игроком', exact: true }).click()
  await expect(page.getByRole('region', { name: 'Черновики оценок' })).toHaveCount(0)
  await page.getByRole('button', { name: 'Сменить роль', exact: true }).click()
  await page.getByRole('button', { name: 'Войти администратором', exact: true }).click()
  const otherClient = await (await request.post('/api/auth/demo/admin')).json()
  headers.Authorization = `Bearer ${otherClient.token}`
  await expect(page.getByRole('region', { name: 'Черновики оценок' })).toContainText(
    'Есть несохранённые изменения: 1',
  )
  await page.getByRole('button', { name: 'Игроки', exact: true }).click()
  await search.fill(two.alias)
  await expect(page.getByLabel(`Моя защита: ${two.alias}`)).toHaveValue('3')
  await page.getByLabel(`Моя атака: ${two.alias}`).fill('1')
  await send(`/players/${two.id}/ratings`, 'PUT', {
    position: 'field',
    attack: 5,
    defense: 5,
    revision: 0,
  })
  const save = page.getByRole('button', { name: `Сохранить оценки: ${two.alias}`, exact: true })
  await save.click()
  await expect(page.locator('.catalog-feedback')).toContainText('На сервере: А 5 · З 5')
  await expect(save).toBeDisabled()
  await page.getByRole('button', { name: 'Использовать мой ввод', exact: true }).click()
  await save.click()
  await expect(
    page.getByRole('status').filter({ hasText: `Оценки сохранены: ${two.alias}` }),
  ).toBeVisible()
  await expect(save).toBeDisabled()
  expect((await send(`/players/${two.id}/ratings/field`)).own).toMatchObject({
    attack: 1,
    defense: 3,
    revision: 2,
  })
})

test('compact section headers retain controls and long profile dialogs keep close and keyboard navigation available', async ({
  page,
  request,
}) => {
  const { send } = await setup(page, request)
  const player = await send('/players/guests', 'POST', {
    alias: `Компактный профиль ${Date.now()}`,
  })
  await page.goto('/')
  for (const width of [320, 390, 1440]) {
    await page.setViewportSize({ width, height: 740 })
    for (const name of ['Игроки', 'Архив', 'Прогнозы', 'Профиль']) {
      await page.getByRole('button', { name, exact: true }).click()
      await expect(
        page.getByRole('combobox', { name: 'Период статистики', exact: true }),
      ).toBeVisible()
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
        true,
      )
      if (name === 'Игроки') {
        await expect(page.getByRole('searchbox', { name: 'Поиск игроков' })).toBeVisible()
        await expect(
          page.getByRole('checkbox', { name: 'Только участники предыдущей игры' }),
        ).toBeVisible()
        expect((await page.locator('.catalog-person').first().boundingBox())!.y).toBeLessThan(740)
      }
      await page.screenshot({ path: `test-results/compact-${name}-${width}.png`, fullPage: false })
    }
  }
  await page.setViewportSize({ width: 320, height: 640 })
  await page.getByRole('button', { name: 'Игроки', exact: true }).click()
  await page.getByRole('searchbox', { name: 'Поиск игроков' }).fill(player.alias)
  await page.locator('.catalog-person .player-name').click()
  const modal = page.getByRole('dialog')
  const close = modal.getByRole('button', { name: 'Закрыть', exact: true })
  await modal.getByText('Как оценили другие игроки', { exact: true }).waitFor()
  await modal.evaluate((el) => {
    el.scrollTop = el.scrollHeight
  })
  const box = await modal.boundingBox(),
    button = await close.boundingBox()
  expect(button!.y).toBeGreaterThanOrEqual(box!.y)
  expect(button!.y + button!.height).toBeLessThan(box!.y + 90)
  await close.focus()
  await page.keyboard.press('Shift+Tab')
  await expect(modal.locator('summary').last()).toBeFocused()
  await page.keyboard.press('Tab')
  await expect(close).toBeFocused()
  await close.click()
  await expect(page.getByRole('dialog')).toHaveCount(0)
})
