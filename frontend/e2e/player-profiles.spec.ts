import { expect, test, type Locator, type Page } from '@playwright/test'
import type { Match, Player } from '../src/types'

for (const games of [0, 1, 3, 5, 7]) {
  test(`recent results: ${games} games show up to five round dots from oldest to newest`, async ({
    page,
    request,
  }) => {
    const member = await (await request.post('/api/auth/demo/player')).json()
    const matches = Array.from({ length: games }, (_, index) => ({
      match_id: 1000 + index,
      starts_at: `2026-10-${20 - index}T20:00:00+03:00`,
      team: 'white',
      score: { white: index % 3 === 0 ? 2 : 1, black: index % 3 === 2 ? 2 : 1 },
      goals: 0,
      assists: 0,
    }))
    await page.route(`**/api/players/${member.player.id}/stats*`, (route) =>
      route.fulfill({
        json: {
          player_id: member.player.id,
          alias: member.player.alias,
          games,
          wins: 0,
          draws: 0,
          losses: 0,
          goals: 0,
          assists: 0,
          win_rate: games ? 0 : null,
          matches,
          partners: [],
        },
      }),
    )
    await page.addInitScript(
      (token) => sessionStorage.setItem('fczhk-session', token),
      member.token,
    )
    await page.goto('/')
    await page.getByRole('button', { name: 'Профиль', exact: true }).click()
    await expect(
      page.getByRole('heading', { name: `Статистика: ${member.player.alias}`, exact: true }),
    ).toBeVisible()
    const dots = page.locator('.form-dot')
    await expect(dots).toHaveCount(Math.min(5, games))
    await expect(page.getByText('От новой к старой', { exact: true })).toHaveCount(0)
    await expect(page.getByText('От старой к новой', { exact: true })).toHaveCount(0)
    if (!games) {
      await expect(page.locator('.recent-form')).toHaveCount(0)
      return
    }
    const expected = matches.slice(0, 5).reverse()
    for (const [index, match] of expected.entries()) {
      const outcome =
        match.score.white > match.score.black
          ? 'win'
          : match.score.white === match.score.black
            ? 'draw'
            : 'loss'
      await expect(dots.nth(index)).toHaveClass(`form-dot ${outcome}`)
      await expect(dots.nth(index)).toHaveAttribute(
        'aria-label',
        new RegExp(`^${match.starts_at.slice(8, 10)}\\.10\\.2026:`),
      )
    }
    for (const width of [320, 390, 1440]) {
      await page.setViewportSize({ width, height: 900 })
      const sizes = await dots.evaluateAll((items) =>
        items.map((item) => ({
          width: item.getBoundingClientRect().width,
          height: item.getBoundingClientRect().height,
          padding: getComputedStyle(item).padding,
        })),
      )
      expect(sizes).toEqual(expected.map(() => ({ width: 18, height: 18, padding: '0px' })))
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
        true,
      )
      await page.screenshot({
        path: `test-results/recent-results-${games}-${width}.png`,
        fullPage: true,
      })
    }
  })
}

async function openProfile(page: Page, name: Locator, alias: string) {
  await name.click()
  const profile = page.getByRole('dialog', { name: 'Профиль игрока', exact: true })
  await expect(
    profile.getByRole('heading', { name: `Статистика: ${alias}`, exact: true }),
  ).toBeVisible()
  await expect(profile.getByRole('heading', { name: 'Оценки игрока', exact: true })).toBeVisible()
  await profile.getByRole('button', { name: 'Закрыть', exact: true }).click()
  await expect(profile).toHaveCount(0)
}

for (const role of ['admin', 'player']) {
  test(`${role} can rate another player from the profile and return; own profile has no rating action`, async ({
    page,
    request,
  }) => {
    const member = await (await request.post(`/api/auth/demo/${role}`)).json()
    const headers = { Authorization: `Bearer ${member.token}` }
    const people: Player[] = await (await request.get('/api/players', { headers })).json()
    const other = people.find((p) => p.id !== member.player.id && !p.shared_keeper)!
    await page.addInitScript(
      (token) => sessionStorage.setItem('fczhk-session', token),
      member.token,
    )
    await page.goto('/')
    await page.getByRole('button', { name: 'Игроки', exact: true }).click()
    const search = page.getByRole('searchbox', { name: 'Поиск игроков', exact: true })
    await search.fill(other.alias)
    await page
      .locator('.catalog-person')
      .getByRole('button', { name: other.alias, exact: true })
      .click()
    const profile = page.getByRole('dialog', { name: 'Профиль игрока', exact: true })
    await profile.getByRole('button', { name: 'Оценить игрока', exact: true }).click()
    const ratings = page.getByRole('dialog', { name: 'Оценки игроков', exact: true })
    await expect(ratings.getByLabel('Оцениваемый игрок')).toHaveValue(String(other.id))
    await ratings.getByRole('button', { name: 'Полевой', exact: true }).click()
    await expect(
      ratings.getByRole('button', { name: 'Сохранить оценку', exact: true }),
    ).toBeEnabled()
    await ratings.getByLabel('Оценка атаки').fill('2.4')
    await ratings.getByLabel('Оценка защиты').fill('3.6')
    await ratings.getByRole('button', { name: 'Сохранить оценку', exact: true }).click()
    await expect(
      ratings.getByRole('button', { name: 'Сохранить оценку', exact: true }),
    ).toBeEnabled()
    const saved = await (
      await request.get(`/api/players/${other.id}/ratings/field`, { headers })
    ).json()
    expect(saved.own.attack).toBe(2.4)
    expect(saved.own.defense).toBe(3.6)
    await ratings.getByRole('button', { name: 'Закрыть', exact: true }).click()
    await expect(
      profile.getByRole('heading', { name: `Статистика: ${other.alias}`, exact: true }),
    ).toBeVisible()
    for (const width of [320, 390, 1440]) {
      await page.setViewportSize({ width, height: 900 })
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
        true,
      )
    }
    await profile.getByRole('button', { name: 'Закрыть', exact: true }).click()
    await search.fill(member.player.alias)
    await page
      .locator('.catalog-person')
      .getByRole('button', { name: member.player.alias, exact: true })
      .click()
    await expect(
      profile.getByRole('heading', { name: `Статистика: ${member.player.alias}`, exact: true }),
    ).toBeVisible()
    await expect(profile.getByRole('button', { name: 'Оценить игрока', exact: true })).toHaveCount(
      0,
    )
    await profile.getByRole('button', { name: 'Закрыть', exact: true }).click()
    await page.getByRole('button', { name: 'Профиль', exact: true }).click()
    await expect(
      page.getByRole('heading', { name: `Статистика: ${member.player.alias}`, exact: true }),
    ).toBeVisible()
    await expect(page.getByRole('button', { name: 'Оценить игрока', exact: true })).toHaveCount(0)
  })
}

test('catalog names open profiles by keyboard and ratings are part of the statistics overview', async ({
  page,
  request,
}) => {
  const { token } = await (await request.post('/api/auth/demo/admin')).json()
  const headers = { Authorization: `Bearer ${token}` }
  const me: Player = await (await request.get('/api/me', { headers })).json()
  const players: Player[] = await (await request.get('/api/players', { headers })).json()
  const ratings = {
    field: { attack: 0, defense: 4.2, count: 2 },
    keeper: { attack: null, defense: 3.5, count: 1 },
  }
  const person = players.find((p) => p.id !== me.id && !p.shared_keeper)!
  await page.route('**/api/me', (route) => route.fulfill({ json: { ...me, ratings } }))
  await page.route('**/api/players', (route) =>
    route.fulfill({ json: players.map((p) => ({ ...p, ratings })) }),
  )
  await page.addInitScript((value) => sessionStorage.setItem('fczhk-session', value), token)
  await page.goto('/')
  await page.getByRole('button', { name: 'Игроки', exact: true }).click()
  await page.getByRole('searchbox', { name: 'Поиск игроков', exact: true }).fill(person.alias)
  const card = page.locator('.catalog-person').filter({ hasText: person.alias })
  await expect(card).not.toHaveAttribute('open')
  await card.getByRole('button', { name: person.alias, exact: true }).focus()
  await page.keyboard.press('Enter')
  const profile = page.getByRole('dialog', { name: 'Профиль игрока', exact: true })
  await expect(
    profile.getByRole('heading', { name: `Статистика: ${person.alias}`, exact: true }),
  ).toBeVisible()
  const averages = profile.getByLabel(`Средние оценки: ${person.alias}`, { exact: true })
  await expect(averages).toContainText('0')
  await expect(averages).toContainText('4,2')
  await expect(averages).toContainText('3,5')
  for (const width of [320, 390, 1440]) {
    await page.setViewportSize({ width, height: 900 })
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  }
  await page.screenshot({ path: 'test-results/player-profile-ratings.png', fullPage: true })
  await page.keyboard.press('Escape')
  await expect(card).not.toHaveAttribute('open')
  await expect(page.getByRole('searchbox', { name: 'Поиск игроков', exact: true })).toHaveValue(
    person.alias,
  )
  await page.getByRole('button', { name: 'Профиль', exact: true }).click()
  await expect(page.getByLabel('Разделы профиля').getByRole('tab')).toHaveText([
    'Статистика',
    'Настройки',
  ])
  await expect(page.locator('.profile-ratings')).toContainText('Оценки игрока')
  await expect(page.getByLabel(`Средние оценки: ${me.alias}`, { exact: true })).toContainText('4,2')
  await page.getByRole('tab', { name: 'Настройки', exact: true }).click()
  await expect(page.locator('.profile-ratings')).toBeHidden()
  await page.getByRole('tab', { name: 'Статистика', exact: true }).click()
  await expect(page.locator('.profile-ratings')).toBeVisible()
})

test('player names open profiles from registrations, forecasts, auctions, pitch, archive and administration', async ({
  page,
  request,
}) => {
  const { token } = await (await request.post('/api/auth/demo/admin')).json()
  const headers = { Authorization: `Bearer ${token}` }
  const match: Match = await (await request.get('/api/matches/current', { headers })).json()
  const members = match.registrations.filter((r) => r.position === 'field').slice(0, 2)
  const [person, partner] = members
  let current: Match = {
    ...match,
    status: 'approved',
    result: null,
    auction_status: 'completed',
    registrations: members.map((r, index) => ({
      ...r,
      selected: true,
      team: index ? 'black' : 'white',
    })),
  }
  const participants = members.map((r, index) => ({
    ...r,
    registration_id: r.id,
    attack: r.rating.attack,
    defense: r.rating.defense,
    game_mu: null,
    team: index ? 'black' : 'white',
  }))
  const assignments = Object.fromEntries(participants.map((p) => [p.registration_id, p.team]))
  await page.route('**/api/matches/current', (route) => route.fulfill({ json: current }))
  await page.route(`**/api/matches/${match.id}`, (route) => route.fulfill({ json: current }))
  await page.route(`**/api/matches/${match.id}/lineup`, (route) =>
    route.fulfill({
      json: {
        version: match.version,
        roster_version: match.roster_version,
        fingerprint: 'profiles',
        players: participants,
        official_players: current.result ? participants : null,
        assignments,
        placements: {},
        editable: !current.result,
        min_field_players: 2,
        require_two_keepers: false,
        auction: null,
      },
    }),
  )
  await page.route(`**/api/matches/${match.id}/predictions`, (route) =>
    route.fulfill({
      json: {
        server_time: '2026-01-02T20:00:00+03:00',
        deadline: '2026-01-01T20:00:00+03:00',
        available: false,
        closed: true,
        approved_version: match.version,
        count: 1,
        mine: null,
        forecasts: [
          {
            player_id: person.player_id,
            alias: person.alias,
            white_score: 1,
            black_score: 0,
            points: null,
          },
        ],
        actual: null,
      },
    }),
  )
  await page.route(`**/api/matches/${match.id}/auction`, (route) =>
    route.fulfill({
      json: {
        id: 123,
        revision: 1,
        status: 'completed',
        side: null,
        budgets: { white: 100, black: 100 },
        limits: { white: 1, black: 1 },
        captains: { white: person.player_id, black: partner.player_id },
        participants,
        assignments,
        automatic: [],
        prices: {},
        current: null,
        lots: [
          {
            id: 'lot',
            number: 1,
            round: 1,
            player: participants[0],
            winner: 'white',
            white_bid: 1,
            black_bid: 0,
          },
        ],
      },
    }),
  )
  await page.addInitScript((value) => sessionStorage.setItem('fczhk-session', value), token)
  await page.goto(`/?game=${match.id}`)
  await page.getByRole('tab', { name: 'Обзор', exact: true }).click()
  await openProfile(
    page,
    page.locator('.roster-name').getByRole('button', { name: person.alias, exact: true }),
    person.alias,
  )
  await expect(page.getByRole('tab', { name: 'Обзор', exact: true })).toHaveAttribute(
    'aria-selected',
    'true',
  )
  await page.getByRole('tab', { name: 'Обзор', exact: true }).click()
  await expect(page.locator('.game-prediction-top')).toBeVisible()
  await openProfile(
    page,
    page.locator('.forecast-row').getByRole('button', { name: person.alias, exact: true }),
    person.alias,
  )
  await page.getByRole('button', { name: 'Открыть аукцион', exact: true }).click()
  await openProfile(
    page,
    page.locator('.auction-budgets').getByRole('button', { name: person.alias, exact: true }),
    person.alias,
  )
  await page.getByText('История лотов (1)', { exact: true }).click()
  await openProfile(
    page,
    page.locator('.auction-history').getByRole('button', { name: person.alias, exact: true }),
    person.alias,
  )
  await page.goto(`/?game=${match.id}&screen=lineup`)
  const piece = page.locator('.tactics-token').filter({ hasText: person.alias })
  const before = await piece.getAttribute('style')
  await openProfile(
    page,
    piece.getByRole('button', { name: person.alias, exact: true }),
    person.alias,
  )
  await expect(piece).toHaveAttribute('style', before!)
  if ((await page.locator('.tactics-roster').getAttribute('open')) === null)
    await page.locator('.tactics-roster summary').click()
  await openProfile(
    page,
    page.locator('.tactics-roster').getByRole('button', { name: person.alias, exact: true }),
    person.alias,
  )
  current = {
    ...current,
    status: 'completed',
    result: {
      exists: true,
      completed: true,
      version: match.version,
      score: { white: 1, black: 0 },
      participants: current.registrations.map((r) => ({
        player_id: r.player_id,
        alias: r.alias,
        team: r.team!,
        position: r.position,
      })),
      goals: [
        {
          id: 'goal',
          team: 'white',
          kind: 'own_goal',
          author_id: partner.player_id,
          assist_id: null,
        },
      ],
    },
  }
  await page.goto(`/?game=${match.id}`)
  await openProfile(
    page,
    page
      .locator('.archive-player-ratings')
      .getByRole('button', { name: person.alias, exact: true }),
    person.alias,
  )
  await openProfile(
    page,
    page.locator('.archive-goals').getByRole('button', { name: partner.alias, exact: true }),
    partner.alias,
  )
  await page.getByRole('button', { name: 'Настройки', exact: true }).click()
  await page.getByRole('tab', { name: 'Администраторы', exact: true }).click()
  const admin = page
    .getByRole('region', { name: 'Администраторы', exact: true })
    .locator('.player-name')
    .first()
  const alias = await admin.innerText()
  await openProfile(page, admin, alias)
})
