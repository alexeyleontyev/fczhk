import { test, expect } from '@playwright/test'
import { answerConfirmation } from './confirmation-helpers'

test('admin expands a full game to 18+2 and both previews keep two subs per team', async ({
  page,
  request,
}) => {
  const auth = await (await request.post('/api/auth/demo/admin')).json()
  async function send(path: string, method = 'GET', data?: object) {
    const response = await request.fetch('/api' + path, {
      method,
      data,
      headers: { Authorization: `Bearer ${auth.token}` },
    })
    expect(response.ok(), await response.text()).toBe(true)
    return response.json()
  }
  let m = await send('/matches', 'POST', {
    starts_at: '2077-03-12T20:30:00+03:00',
    location: 'Две замены в каждой команде',
  })
  const players = []
  for (let i = 0; i < 20; i++) {
    const p = await send('/players/guests', 'POST', { alias: `Расширенный ${m.id} ${i}` })
    players.push(p)
    if (i < 18)
      await send(`/players/${p.id}/ratings`, 'PUT', {
        position: 'field',
        attack: 3,
        defense: 3,
        revision: 0,
      })
    if (i < 16 || i >= 18)
      m = await send(`/matches/${m.id}/participants`, 'POST', {
        version: m.version,
        player_id: p.id,
        position: i < 16 ? 'field' : 'keeper',
      })
  }
  m = await send(`/matches/${m.id}/actions/open`, 'POST', { version: m.version })
  await page.addInitScript((token) => sessionStorage.setItem('fczhk-session', token), auth.token)
  await page.goto(`/?game=${m.id}`)
  await page.getByRole('button', { name: 'Изменить параметры', exact: true }).click()
  const form = page.getByRole('dialog', { name: 'Параметры игры', exact: true })
  await expect(form.getByLabel('Полевых в сборе · обе команды', { exact: true })).toHaveValue('16')
  await form.getByLabel('Полевых в сборе · обе команды', { exact: true }).fill('18')
  for (const width of [320, 768]) {
    await page.setViewportSize({ width, height: 1000 })
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  }
  await answerConfirmation(
    form.getByRole('button', { name: 'Сохранить параметры', exact: true }),
    true,
    '18 полевых + 2 вратаря',
  )
  await expect(form).toHaveCount(0)
  for (const person of players.slice(16, 18)) {
    await page.getByRole('button', { name: 'Добавить игрока', exact: true }).click()
    const include = page.getByRole('dialog', { name: 'Добавить в состав', exact: true })
    await include
      .getByRole('combobox', { name: 'Игрок', exact: true })
      .selectOption(String(person.id))
    await include.getByRole('button', { name: 'Добавить в состав', exact: true }).click()
    await expect(include).toHaveCount(0)
  }
  await page.getByRole('button', { name: 'Утвердить составы', exact: true }).click()
  await page.getByRole('dialog').getByRole('button', { name: 'Да', exact: true }).click()
  await page.getByRole('tab', { name: 'Составы', exact: true }).click()
  for (const name of ['По оценкам', 'OpenSkill']) {
    await page.getByRole('button', { name, exact: true }).click()
    await expect(page.locator('.tactics-token')).toHaveCount(20)
    for (const team of ['white', 'black']) {
      const tokens = page.locator(`.tactics-token.${team}`)
      await expect(tokens).toHaveCount(10)
      const depths = await tokens.evaluateAll((elements) =>
        elements.map((e) => parseFloat((e as HTMLElement).style.top)),
      )
      // Keeper and two substitutes sit by the goal; seven fields remain in play.
      expect(
        depths.filter((y) => Math.abs(y - (team === 'black' ? 6.5 : 93.5)) < 0.01),
      ).toHaveLength(3)
    }
  }
  const confirmed = page.waitForResponse(
    (response) =>
      response.url().endsWith(`/matches/${m.id}/lineup/confirm`) &&
      response.request().method() === 'POST',
  )
  await page.getByRole('button', { name: 'Утвердить состав', exact: true }).click()
  expect((await confirmed).ok()).toBe(true)
  m = await send(`/matches/${m.id}`)
  expect(m.status).toBe('approved')
  expect(m.registrations.filter((r: { selected: boolean }) => r.selected)).toHaveLength(20)
})
