import { expect, test } from '@playwright/test'
import type { Match, Player } from '../src/types'

test('quick final score creates goal placeholders and preserves filled authors', async ({
  page,
  request,
}) => {
  const admin = await (await request.post('/api/auth/demo/admin')).json()
  const member = await (await request.post('/api/auth/demo/player')).json()
  const headers = { Authorization: `Bearer ${admin.token}` }
  async function send(path: string, data: object, method = 'POST') {
    const response = await request.fetch(`/api${path}`, { method, headers, data })
    expect(response.ok(), await response.text()).toBe(true)
    return response.json()
  }
  const starts = new Date(
    Date.UTC(1985, 0, 1) + Math.floor(Math.random() * 250) * 86400000,
  ).toISOString()
  let m = await send('/matches', { starts_at: starts, location: 'Быстрый счёт' })
  for (const p of [admin.player, member.player])
    m = await send(`/matches/${m.id}/participants`, {
      version: m.version,
      player_id: p.id,
      position: 'field',
    })
  for (const action of ['open', 'finalize'])
    m = await send(`/matches/${m.id}/actions/${action}`, { version: m.version })
  m = await send(
    `/matches/${m.id}/teams`,
    {
      version: m.version,
      assignments: Object.fromEntries(
        m.registrations.map((r: { id: number }, i: number) => [r.id, i ? 'black' : 'white']),
      ),
    },
    'PUT',
  )
  m = await send(`/matches/${m.id}/actions/approve`, { version: m.version })
  await page.addInitScript((token) => sessionStorage.setItem('fczhk-session', token), admin.token)
  await page.goto(`/?game=${m.id}`)
  await page.getByRole('tab', { name: 'Итог', exact: true }).click()
  await page.getByRole('button', { name: 'Внести результат', exact: true }).click()
  const form = page.getByRole('form', { name: 'Быстрый ввод счёта', exact: true })
  async function setScore(white: number, black: number) {
    await form.getByLabel('Счёт белых', { exact: true }).fill(String(white))
    await form.getByLabel('Счёт чёрных', { exact: true }).fill(String(black))
    await form.getByRole('button', { name: 'Создать записи голов', exact: true }).click()
  }
  await setScore(2, 1)
  await expect(page.locator('.goal-editor')).toHaveCount(3)
  const blackGoal = page.locator('.goal-editor').last()
  await blackGoal.getByRole('checkbox', { name: 'Автогол', exact: true }).check()
  await expect(
    blackGoal.getByRole('combobox', { name: 'Голевая передача', exact: true }),
  ).toHaveCount(0)
  await expect(
    blackGoal
      .getByRole('combobox', { name: 'Автор гола', exact: true })
      .getByRole('option', { name: admin.player.alias, exact: true }),
  ).toHaveCount(1)
  await expect(
    blackGoal
      .getByRole('combobox', { name: 'Автор гола', exact: true })
      .getByRole('option', { name: member.player.alias, exact: true }),
  ).toHaveCount(0)
  await blackGoal.getByRole('checkbox', { name: 'Автогол', exact: true }).uncheck()
  await expect(
    blackGoal.getByRole('combobox', { name: 'Голевая передача', exact: true }),
  ).toBeVisible()
  const author = page
    .locator('.goal-editor')
    .first()
    .getByRole('combobox', { name: 'Автор гола', exact: true })
  await author.selectOption(String(admin.player.id))
  await setScore(1, 0)
  await expect(page.locator('.goal-editor')).toHaveCount(1)
  await expect(author).toHaveValue(String(admin.player.id))
  await setScore(0, 0)
  await expect(page.getByRole('alert')).toContainText(
    'Сначала исправьте или удалите лишние события',
  )
  await expect(page.locator('.goal-editor')).toHaveCount(1)
  await setScore(8, 6)
  await expect(page.locator('.goal-editor')).toHaveCount(14)
  await expect(author).toHaveValue(String(admin.player.id))
  await page.getByRole('button', { name: 'Завершить матч', exact: true }).click()
  await expect(page.locator('.archive-scoreboard')).toContainText('8 : 6')
  const saved = await (await request.get(`/api/matches/${m.id}/result`, { headers })).json()
  expect(saved.goals).toHaveLength(14)
  expect(
    saved.goals.filter((g: { author_id: number | null }) => g.author_id === admin.player.id),
  ).toHaveLength(1)
})

test('player payment and administrator confirmation have independent green and red states', async ({
  page,
  request,
  browser,
}) => {
  const admin = await (await request.post('/api/auth/demo/admin')).json()
  const member = await (await request.post('/api/auth/demo/player')).json()
  const headers = { Authorization: `Bearer ${admin.token}` }
  const starts = new Date(
    Date.UTC(2095, 0, 1) + Math.floor(Math.random() * 250) * 86400000,
  ).toISOString()
  let match: Match = await (
    await request.post('/api/matches', {
      headers,
      data: { starts_at: starts, location: 'Проверка оплаты' },
    })
  ).json()
  match = await (
    await request.post(`/api/matches/${match.id}/actions/open`, {
      headers,
      data: { version: match.version },
    })
  ).json()
  const playerHeaders = { Authorization: `Bearer ${member.token}` }
  await request.post(`/api/matches/${match.id}/join`, {
    headers: playerHeaders,
    data: { position: 'field' },
  })
  await page.addInitScript((token) => sessionStorage.setItem('fczhk-session', token), member.token)
  await page.goto(`/?game=${match.id}`)
  const main = page.getByRole('region', { name: 'Основной список', exact: true })
  await expect(main).toContainText(member.player.alias)
  await page.getByRole('button', { name: 'Я оплатил', exact: true }).click()
  const statuses = main.getByRole('group', {
    name: `Оплата и подтверждение: ${member.player.alias}`,
    exact: true,
  })
  await expect(statuses.locator('.payment-status').first()).toHaveText('Оплачен')
  await expect(statuses.locator('.payment-status').first()).toHaveClass(/positive/)
  await expect(statuses.locator('.payment-status').last()).toHaveText('Не подтверждено')
  await expect(statuses.locator('.payment-status').last()).toHaveClass(/negative/)
  const reported = await (await request.get(`/api/matches/${match.id}`, { headers })).json()
  expect(reported.registrations[0].paid).toBe(false)
  expect(reported.registrations[0].selected).toBe(false)
  const context = await browser.newContext()
  try {
    const adminPage = await context.newPage()
    await adminPage.addInitScript(
      (token) => sessionStorage.setItem('fczhk-session', token),
      admin.token,
    )
    await adminPage.goto(`/?game=${match.id}`)
    const adminStatuses = adminPage
      .getByRole('region', { name: 'Основной список', exact: true })
      .getByRole('group', { name: `Оплата и подтверждение: ${member.player.alias}`, exact: true })
    await expect(adminStatuses).toBeVisible()
    await adminPage.evaluate(() => document.fonts.ready)
    const widths = () =>
      adminStatuses
        .locator('.payment-status')
        .evaluateAll((buttons) => buttons.map((button) => button.getBoundingClientRect().width))
    const initialWidths = await widths()
    expect(initialWidths[0]).toBe(initialWidths[1])
    await adminPage
      .getByRole('button', { name: `Подтвердить оплату: ${member.player.alias}`, exact: true })
      .click()
    await page.getByRole('button', { name: 'Обновить игру', exact: true }).click()
    await expect(statuses.locator('.payment-status.positive')).toHaveCount(2)
    await expect(page.getByRole('button', { name: 'Я оплатил', exact: true })).toHaveCount(0)
    expect(await widths()).toEqual(initialWidths)
    await adminStatuses
      .getByRole('button', { name: `Отменить отметку оплаты: ${member.player.alias}`, exact: true })
      .click()
    await expect(adminStatuses.locator('.payment-status').first()).toHaveText('Не оплачен')
    await expect(adminStatuses.locator('.payment-status').first()).toHaveClass(/negative/)
    await expect(adminStatuses.locator('.payment-status').last()).toHaveText('Подтверждено')
    await expect(adminStatuses.locator('.payment-status').last()).toHaveClass(/positive/)
    expect(await widths()).toEqual(initialWidths)
    await adminStatuses
      .getByRole('button', { name: `Отметить оплату: ${member.player.alias}`, exact: true })
      .click()
    await expect(adminStatuses.locator('.payment-status.positive')).toHaveCount(2)
    expect(await widths()).toEqual(initialWidths)
    await adminStatuses
      .getByRole('button', { name: `Снять подтверждение: ${member.player.alias}`, exact: true })
      .click()
    await expect(adminStatuses.locator('.payment-status').first()).toHaveText('Оплачен')
    await expect(adminStatuses.locator('.payment-status').last()).toHaveText('Не подтверждено')
    expect(await widths()).toEqual(initialWidths)
    await adminStatuses
      .getByRole('button', { name: `Отменить отметку оплаты: ${member.player.alias}`, exact: true })
      .click()
    await expect(adminStatuses.locator('.payment-status.negative')).toHaveCount(2)
    expect(await widths()).toEqual(initialWidths)
    await expect(adminPage.getByText('Статус оплаты', { exact: true })).toHaveCount(0)
  } finally {
    await context.close()
  }
})

test('collection overview separates 16 field players and 2 keepers from the reserve', async ({
  page,
  request,
}) => {
  const { token } = await (await request.post('/api/auth/demo/admin')).json()
  const headers = { Authorization: `Bearer ${token}` }
  const base: Match = await (await request.get('/api/matches/current', { headers })).json()
  const players: Player[] = await (await request.get('/api/players', { headers })).json()
  const sample = base.registrations[0]
  const registrations = players.slice(0, 21).map((p, i) => ({
    ...sample,
    id: i + 1,
    player_id: p.id,
    alias: p.alias,
    paid: i % 3 === 0,
    payment_reported: i % 3 === 1,
    selected: false,
    in_main: i < 16 || (i >= 18 && i < 20),
    position: i < 18 ? 'field' : 'keeper',
    queue: i < 18 ? i + 1 : i - 17,
    guest: p.guest,
  }))
  const match = { ...base, status: 'open', result: null, registrations }
  await page.route(`**/api/matches/${base.id}`, (route) => route.fulfill({ json: match }))
  await page.addInitScript((value) => sessionStorage.setItem('fczhk-session', value), token)
  await page.goto(`/?game=${base.id}`)
  const main = page.getByRole('region', { name: 'Основной список', exact: true })
  const reserve = page.getByRole('region', { name: 'Резерв', exact: true })
  await expect(main.locator('.roster-row')).toHaveCount(18)
  await expect(main).toContainText('Полевые: 16 / 16')
  await expect(main).toContainText('Вратари: 2 / 2')
  await expect(reserve.locator('.roster-row')).toHaveCount(3)
  await expect(page.getByRole('tab', { name: 'Участники', exact: true })).toHaveCount(0)
  await expect(page.getByRole('tab', { name: 'Управление', exact: true })).toHaveCount(0)
  await expect(page.getByText('Сбор ещё не утверждён', { exact: true })).toHaveCount(0)
  await expect(page.getByText('Подробности записи', { exact: true })).toHaveCount(0)
  await expect(main.locator('time')).toHaveCount(18)
  await expect(main.locator('time').first()).toContainText('МСК')
  const controls = page.getByRole('region', { name: 'Управление игрой', exact: true })
  for (const name of [
    'Утвердить составы',
    'Изменить параметры',
    'История изменений',
    'Новая игра',
    'Отменить игру',
  ]) {
    await expect(controls.getByRole('button', { name, exact: true })).toBeVisible()
  }
  await expect(controls.getByRole('button', { name: 'Добавить игрока', exact: true })).toHaveCount(
    0,
  )
  const participants = page.locator('section.panel').filter({
    has: page.getByRole('heading', { name: 'Участники', exact: true }),
  })
  await expect(
    participants.getByRole('button', { name: 'Добавить игрока', exact: true }),
  ).toBeVisible()
  expect(
    await controls.evaluate((panel) => {
      const roster = document.querySelector('.roster-main')!
      return Boolean(panel.compareDocumentPosition(roster) & Node.DOCUMENT_POSITION_FOLLOWING)
    }),
  ).toBe(true)
  await expect(main).toContainText('Не подтверждено')
  await expect(main).toContainText('Подтверждено')
  for (const width of [320, 390, 1440]) {
    await page.setViewportSize({ width, height: 900 })
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
    await page.screenshot({ path: `test-results/collection-statuses-${width}.png`, fullPage: true })
  }
})

test('confirmation names reserve replacements, No leaves the collection open and Yes confirms', async ({
  page,
  request,
}) => {
  const { token } = await (await request.post('/api/auth/demo/admin')).json()
  const headers = { Authorization: `Bearer ${token}` }
  const base: Match = await (await request.get('/api/matches/current', { headers })).json()
  const people: Player[] = await (await request.get('/api/players', { headers })).json()
  const sample = base.registrations[0]
  const [unpaid, fixed, keeper, fieldReserve, keeperReserve, reportedReserve] = people.filter(
    (p) => !p.shared_keeper,
  )
  let match: Match = {
    ...base,
    id: 988031,
    status: 'open',
    result: null,
    starts_at: '2099-01-01T17:00:00Z',
    field_limit: 2,
    keeper_limit: 1,
    registrations: [unpaid, fixed, keeper, fieldReserve, keeperReserve, reportedReserve].map(
      (p, i) => ({
        ...sample,
        id: i + 1,
        player_id: p.id,
        alias: p.alias,
        forced: i === 1,
        paid: i === 3 || i === 4,
        payment_reported: i === 2 || i === 5,
        in_main: i < 3,
        selected: i === 1 || i === 3 || i === 4,
        position: i === 2 || i === 4 ? 'keeper' : 'field',
        queue: i + 1,
      }),
    ),
  }
  const confirmations: { version: number }[] = []
  await page.route(`**/api/matches/${match.id}`, (route) => route.fulfill({ json: match }))
  await page.route(`**/api/matches/${match.id}/actions/finalize`, (route) => {
    const body = route.request().postDataJSON()
    confirmations.push(body)
    if (body.version !== match.version)
      return route.fulfill({ status: 409, json: { detail: 'Данные изменились. Обновите игру.' } })
    match = {
      ...match,
      status: 'finalized',
      version: match.version + 1,
      registrations: match.registrations.map((r) => ({ ...r, in_main: r.selected })),
    }
    return route.fulfill({ json: match })
  })
  await page.addInitScript((value) => sessionStorage.setItem('fczhk-session', value), token)
  await page.goto(`/?game=${match.id}`)
  await page.getByRole('button', { name: 'Утвердить составы', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: 'Утвердить составы?', exact: true })
  const fields = dialog.getByRole('region', { name: 'Изменения: Полевые', exact: true })
  const keepers = dialog.getByRole('region', { name: 'Изменения: Вратари', exact: true })
  await expect(fields).toContainText(`Не войдут в сбор: ${unpaid.alias}`)
  await expect(fields).toContainText(`Из резерва войдут: ${fieldReserve.alias}`)
  await expect(keepers).toContainText(`Не войдут в сбор: ${keeper.alias}`)
  await expect(keepers).toContainText(`Из резерва войдут: ${keeperReserve.alias}`)
  await expect(dialog.getByRole('button', { name: fixed.alias, exact: true })).toHaveCount(0)
  await expect(
    dialog.getByRole('button', { name: reportedReserve.alias, exact: true }),
  ).toHaveCount(0)
  await expect(dialog).toContainText(
    'Заменить игроков основного списка игроками из резерва и утвердить сбор?',
  )
  await expect(dialog).toContainText('В сборе будет 2 / 2 полевых и 1 / 1 вратарей')
  expect(confirmations).toEqual([])
  await page.screenshot({ path: 'test-results/collection-confirmation-mobile.png', fullPage: true })
  await dialog.getByRole('button', { name: 'Нет', exact: true }).click()
  await expect(dialog).toHaveCount(0)
  expect(confirmations).toEqual([])
  expect(match.status).toBe('open')
  const main = page.getByRole('region', { name: 'Основной список', exact: true })
  await expect(main.getByRole('button', { name: unpaid.alias, exact: true })).toBeVisible()

  // A concurrent payment change requires another explicit decision on the updated list.
  await page.getByRole('button', { name: 'Утвердить составы', exact: true }).click()
  const shownVersion = match.version
  match = { ...match, version: match.version + 1 }
  await dialog.getByRole('button', { name: 'Да', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText('Данные изменились')
  await expect(dialog).toBeVisible()
  expect(match.status).toBe('open')
  expect(confirmations).toEqual([{ version: shownVersion }])
  await dialog.getByRole('button', { name: 'Да', exact: true }).click()
  await expect(dialog).toHaveCount(0)
  expect(confirmations).toEqual([{ version: shownVersion }, { version: shownVersion + 1 }])
  expect(match.status).toBe('finalized')
  await expect(main.getByRole('button', { name: fieldReserve.alias, exact: true })).toBeVisible()
  await expect(main.getByRole('button', { name: keeperReserve.alias, exact: true })).toBeVisible()
  await expect(main.getByRole('button', { name: fixed.alias, exact: true })).toBeVisible()
  await expect(main.getByRole('button', { name: unpaid.alias, exact: true })).toHaveCount(0)
})

test('confirmation explains a shortfall when reserve payments are unconfirmed', async ({
  page,
  request,
}) => {
  const { token } = await (await request.post('/api/auth/demo/admin')).json()
  const headers = { Authorization: `Bearer ${token}` }
  const base: Match = await (await request.get('/api/matches/current', { headers })).json()
  const registrations = base.registrations.map((r) => ({
    ...r,
    paid: false,
    payment_reported: true,
    forced: false,
    selected: false,
  }))
  const match = { ...base, id: 988032, status: 'open', result: null, registrations }
  await page.route(`**/api/matches/${match.id}`, (route) => route.fulfill({ json: match }))
  await page.addInitScript((value) => sessionStorage.setItem('fczhk-session', value), token)
  await page.goto(`/?game=${match.id}`)
  await page.getByRole('button', { name: 'Утвердить составы', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: 'Утвердить составы?', exact: true })
  await expect(dialog).toContainText('В сборе будет 0 / 16 полевых и 0 / 2 вратарей')
  await expect(
    dialog.getByText('В резерве нет игроков этого амплуа с подтверждённой оплатой.'),
  ).toHaveCount(2)
  await expect(dialog.getByText('Из резерва войдут:', { exact: false })).toHaveCount(0)
  await dialog.getByRole('button', { name: 'Нет', exact: true }).click()
  await expect(dialog).toHaveCount(0)
})

test('rated filter keeps zero scores, profile lazily reveals named reviews and five recent outcomes', async ({
  page,
  request,
}) => {
  const { token } = await (await request.post('/api/auth/demo/player')).json()
  const players: Player[] = await (
    await request.get('/api/players', { headers: { Authorization: `Bearer ${token}` } })
  ).json()
  const [person, reviewer, unrated] = players.filter((p) => !p.shared_keeper)
  const rated = { field: { attack: 0, defense: 0 }, keeper: { attack: null, defense: null } }
  const catalog = [
    { ...person, ratings: rated },
    {
      ...reviewer,
      ratings: { field: { attack: null, defense: null }, keeper: { attack: null, defense: 0 } },
    },
    { ...unrated, ratings: undefined },
  ]
  await page.route('**/api/players', (route) => route.fulfill({ json: catalog }))
  await page.route(`**/api/players/${person.id}/stats*`, (route) =>
    route.fulfill({
      json: {
        player_id: person.id,
        alias: person.alias,
        games: 5,
        wins: 2,
        draws: 1,
        losses: 2,
        goals: 0,
        assists: 0,
        win_rate: 40,
        partners: [],
        matches: [2, 0, -1, 1, -2].map((difference, i) => ({
          match_id: 100 + i,
          starts_at: `2026-10-${20 - i}T20:00:00+03:00`,
          team: 'white',
          score: { white: Math.max(difference, 0), black: Math.max(-difference, 0) },
          goals: 0,
          assists: 0,
        })),
      },
    }),
  )
  let reviews = 0
  await page.route(`**/api/players/${person.id}/reviews`, (route) => {
    reviews++
    return route.fulfill({
      json: {
        field: [{ author_id: reviewer.id, author: reviewer.alias, attack: 0, defense: 4.2 }],
        keeper: [],
      },
    })
  })
  await page.addInitScript((value) => sessionStorage.setItem('fczhk-session', value), token)
  await page.goto('/')
  await page.getByRole('button', { name: 'Игроки', exact: true }).click()
  await expect(page.locator('.catalog-person')).toHaveCount(3)
  await page.getByRole('checkbox', { name: 'Только игроки с оценками', exact: true }).check()
  await expect(page.locator('.catalog-person')).toHaveCount(2)
  await page
    .locator('.catalog-person')
    .getByRole('button', { name: person.alias, exact: true })
    .click()
  const profile = page.getByRole('dialog')
  await expect(profile.locator('.form-dot')).toHaveCount(5)
  await expect(profile.locator('.form-dot.win')).toHaveCount(2)
  await expect(profile.locator('.form-dot.draw')).toHaveCount(1)
  await expect(profile.locator('.form-dot.loss')).toHaveCount(2)
  expect(reviews).toBe(0)
  await profile.getByText('Как оценили другие игроки', { exact: true }).click()
  await expect(profile.locator('.profile-review')).toContainText(reviewer.alias)
  await expect(profile.locator('.profile-review')).toContainText('4,2')
  expect(reviews).toBe(1)
  await page.setViewportSize({ width: 320, height: 900 })
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  await page.screenshot({ path: 'test-results/profile-reviews-form-mobile.png', fullPage: true })
})

test('Telegram prediction link opens the top form and accepts a category using the matrix', async ({
  page,
  request,
}) => {
  const admin = await (await request.post('/api/auth/demo/admin')).json()
  const member = await (await request.post('/api/auth/demo/player')).json()
  const headers = { Authorization: `Bearer ${admin.token}` }
  async function send(path: string, data: object, method = 'POST') {
    const response = await request.fetch(`/api${path}`, { method, headers, data })
    expect(response.ok(), await response.text()).toBe(true)
    return response.json()
  }
  const starts = new Date(
    Date.UTC(2094, 0, 1) + Math.floor(Math.random() * 250) * 86400000,
  ).toISOString()
  let m = await send('/matches', { starts_at: starts, location: 'Прогноз по категории' })
  for (const p of [admin.player, member.player])
    m = await send(`/matches/${m.id}/participants`, {
      version: m.version,
      player_id: p.id,
      position: 'field',
    })
  for (const action of ['open', 'finalize'])
    m = await send(`/matches/${m.id}/actions/${action}`, { version: m.version })
  m = await send(
    `/matches/${m.id}/teams`,
    {
      version: m.version,
      assignments: Object.fromEntries(
        m.registrations.map((r: { id: number }, i: number) => [r.id, i ? 'black' : 'white']),
      ),
    },
    'PUT',
  )
  m = await send(`/matches/${m.id}/actions/approve`, { version: m.version })
  await page.route('https://telegram.org/js/telegram-web-app.js', (route) =>
    route.fulfill({ contentType: 'application/javascript', body: '' }),
  )
  await page.addInitScript(
    ({ token, id }) => {
      sessionStorage.setItem('fczhk-session', token)
      window.Telegram = {
        WebApp: {
          initData: '',
          initDataUnsafe: { start_param: `game_${id}_prediction` },
          ready() {},
          expand() {},
        },
      }
    },
    { token: member.token, id: m.id },
  )
  await page.goto('/')
  const panel = page.locator('.game-prediction-top .prediction-panel')
  await expect(panel.getByRole('button', { name: 'Сделать прогноз', exact: true })).toBeVisible()
  await expect(page).toHaveURL(
    new RegExp(`screen=prediction.*game=${m.id}|game=${m.id}.*screen=prediction`),
  )
  await panel.getByRole('combobox', { name: 'Исход прогноза', exact: true }).selectOption('Б4')
  await expect(panel.getByLabel('Голы белых', { exact: true })).toBeHidden()
  await panel.getByRole('button', { name: 'Сделать прогноз', exact: true }).click()
  await expect(panel).toContainText('Категория: Б4')
  await panel.getByText('Как начисляются очки', { exact: true }).click()
  await expect(
    panel.locator('.prediction-matrix tbody tr').nth(1).locator('td').first(),
  ).toHaveText('0,5')
  for (const width of [320, 390, 1440]) {
    await page.setViewportSize({ width, height: 900 })
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  }
  await page.screenshot({ path: 'test-results/prediction-matrix-top.png', fullPage: true })
})
