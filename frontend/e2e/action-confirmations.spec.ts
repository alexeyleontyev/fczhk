import { expect, test, type APIRequestContext } from '@playwright/test'
import { answerConfirmation, publicationState } from './confirmation-helpers'
import type { Match, Player } from '../src/types'

function matchState(match: Match) {
  return { ...match, publications: publicationState(match) }
}

async function prepare(request: APIRequestContext, count: number) {
  const admin = await (await request.post('/api/auth/demo/admin')).json()
  const member = await (await request.post('/api/auth/demo/player')).json()
  const headers = { Authorization: `Bearer ${admin.token}` }
  async function send(path: string, method = 'GET', data?: object) {
    const response = await request.fetch(`/api${path}`, { method, headers, data })
    expect(response.ok(), await response.text()).toBe(true)
    return response.json()
  }
  const people: Player[] = await send('/players')
  const selected = [
    people.find((p) => p.id === admin.player.id)!,
    people.find((p) => p.id === member.player.id)!,
    ...people.filter(
      (p) => p.id !== admin.player.id && p.id !== member.player.id && !p.shared_keeper,
    ),
  ]
  const starts = new Date(Date.now() + (6000 + Math.floor(Math.random() * 9000)) * 86400000)
  let match: Match = await send('/matches', 'POST', {
    starts_at: starts.toISOString(),
    location: 'Проверка подтверждений',
  })
  for (const person of selected.slice(0, count)) {
    match = await send(`/matches/${match.id}/participants`, 'POST', {
      version: match.version,
      player_id: person.id,
      position: 'field',
    })
  }
  const first = match.registrations[0]
  match = await send(`/matches/${match.id}/registrations/${first.id}/payment`, 'PUT', {
    version: match.version,
    paid: true,
    reported: true,
  })
  return { token: admin.token, match, selected, send }
}

async function cleanup(send: Awaited<ReturnType<typeof prepare>>['send'], id: number) {
  const m: Match = await send(`/matches/${id}`)
  await send(`/matches/${id}/cancel`, 'POST', {
    version: m.version,
    reason: 'Завершение проверки подтверждений',
  })
}

test('No preserves the collection, payments and publications; Yes performs the reviewed action', async ({
  page,
  request,
}) => {
  const { token, match: original, selected, send } = await prepare(request, 2)
  const id = original.id
  try {
    await page.addInitScript((value) => sessionStorage.setItem('fczhk-session', value), token)
    await page.goto(`/?game=${id}`)
    const open = page.getByRole('button', { name: 'Открыть сбор', exact: true })
    await answerConfirmation(open, false, 'Пост будет отправлен в канал сборов')
    expect(matchState(await send(`/matches/${id}`))).toEqual(matchState(original))
    await answerConfirmation(open, true, 'Открыть сбор?')
    await expect(page.getByRole('button', { name: 'Утвердить составы', exact: true })).toBeVisible()

    await page.getByRole('button', { name: 'Изменить параметры', exact: true }).click()
    const form = page.getByRole('dialog', { name: 'Параметры игры', exact: true })
    await form.getByLabel('Место игры', { exact: true }).fill('Проверенное изменение места')
    const beforeEdit = await send(`/matches/${id}`)
    const save = form.getByRole('button', { name: 'Сохранить параметры', exact: true })
    await answerConfirmation(save, false, 'Новый пост будет отправлен в канал сборов')
    expect(matchState(await send(`/matches/${id}`))).toEqual(matchState(beforeEdit))
    await expect(form).toBeVisible()
    await answerConfirmation(save, true, 'Проверенное изменение места')
    await expect(form).toHaveCount(0)
    let m: Match = await send(`/matches/${id}`)
    expect(m.location).toBe('Проверенное изменение места')
    expect(m.registrations).toEqual(beforeEdit.registrations)

    const remove = page
      .locator('.roster-row')
      .filter({ has: page.getByRole('button', { name: selected[0].alias, exact: true }) })
      .getByRole('button', { name: 'Убрать', exact: true })
    await answerConfirmation(remove, false, 'Обе отметки оплаты будут сброшены')
    expect(matchState(await send(`/matches/${id}`))).toEqual(matchState(m))
    await page.getByRole('button', { name: 'Добавить игрока', exact: true }).click()
    const include = page.getByRole('dialog', { name: 'Добавить в состав', exact: true })
    await include
      .getByRole('combobox', { name: 'Игрок', exact: true })
      .selectOption(String(selected[2].id))
    const replaced = m.registrations.find((r) => r.player_id === selected[0].id)!
    await include
      .getByRole('combobox', { name: 'Кого заменить', exact: true })
      .selectOption(String(replaced.id))
    const add = include.getByRole('button', { name: 'Добавить в состав', exact: true })
    const text = await answerConfirmation(add, false, 'обе отметки оплаты сброшены')
    expect(text).toContain(selected[0].alias)
    expect(text).toContain(selected[2].alias)
    expect(matchState(await send(`/matches/${id}`))).toEqual(matchState(m))
    await expect(include).toBeVisible()
    await answerConfirmation(add, true, 'Заменить')
    await expect(include).toHaveCount(0)
    m = await send(`/matches/${id}`)
    expect(m.registrations.some((r) => r.player_id === selected[0].id)).toBe(false)
    expect(m.registrations.some((r) => r.player_id === selected[2].id)).toBe(true)

    m = await send(`/matches/${id}/actions/finalize`, 'POST', { version: m.version })
    m = await send(`/matches/${id}/teams`, 'PUT', {
      version: m.version,
      assignments: Object.fromEntries(m.registrations.map((r, i) => [r.id, i ? 'black' : 'white'])),
    })
    m = await send(`/matches/${id}/actions/approve`, 'POST', { version: m.version })
    await page.reload()
    const publish = page.getByRole('button', { name: 'Опубликовать составы', exact: true })
    await answerConfirmation(publish, false, 'Опубликовать составы в канале сборов?')
    expect(matchState(await send(`/matches/${id}`))).toEqual(matchState(m))
    await expect(
      page.getByRole('status').filter({ hasText: 'Публикация поставлена в очередь' }),
    ).toHaveCount(0)
    await answerConfirmation(publish, true, '⚪ Белые')
    await expect(
      page.getByRole('status').filter({ hasText: 'Публикация поставлена в очередь' }),
    ).toBeVisible()
    expect(
      (await send(`/matches/${id}`)).publications.filter(
        (p: { kind: string }) => p.kind === 'teams',
      ),
    ).toHaveLength(1)
  } finally {
    await cleanup(send, id)
  }
})

test('auction start, cancellation, manual completion and restart require confirmation', async ({
  page,
  request,
}) => {
  const { token, match: original, selected, send } = await prepare(request, 4)
  const id = original.id
  try {
    let m = await send(`/matches/${id}/actions/open`, 'POST', { version: original.version })
    m = await send(`/matches/${id}/actions/finalize`, 'POST', { version: m.version })
    await page.addInitScript((value) => sessionStorage.setItem('fczhk-session', value), token)
    await page.goto(`/?game=${id}&screen=auction`)
    const panel = page.locator('.auction-panel')
    await panel
      .getByLabel('Капитан: ⚪ Белые', { exact: true })
      .selectOption(String(selected[0].id))
    await panel
      .getByLabel('Капитан: ⚫ Чёрные', { exact: true })
      .selectOption(String(selected[1].id))
    const start = panel.getByRole('button', { name: 'Начать аукцион', exact: true })
    await answerConfirmation(start, false, 'Начать аукцион?')
    expect(await send(`/matches/${id}/auction`)).toBeNull()
    expect(matchState(await send(`/matches/${id}`))).toEqual(matchState(m))
    await answerConfirmation(start, true, 'Капитаны:')
    await expect(panel.getByText('Торги идут', { exact: true })).toBeVisible()
    await panel.getByText('Управление аукционом', { exact: true }).click()
    const auction = await send(`/matches/${id}/auction`)
    const cancel = panel.getByRole('button', { name: 'Отменить аукцион', exact: true })
    const manual = panel.getByRole('button', { name: 'Завершить торги вручную', exact: true })
    await answerConfirmation(cancel, false, 'Возобновить эти торги будет нельзя')
    expect(await send(`/matches/${id}/auction`)).toEqual(auction)
    await answerConfirmation(manual, false, 'Незавершённые ставки будут аннулированы')
    expect(await send(`/matches/${id}/auction`)).toEqual(auction)
    await answerConfirmation(manual, true, 'Завершить торги вручную?')
    await expect(panel.getByText('Завершён вручную', { exact: true })).toBeVisible()
    const finished = await send(`/matches/${id}/auction`)
    await panel.getByText('Начать новый аукцион', { exact: true }).click()
    await answerConfirmation(start, false, 'Начать новый аукцион?')
    expect(await send(`/matches/${id}/auction`)).toEqual(finished)
    await answerConfirmation(start, true, 'История предыдущих торгов сохранится')
    await expect(panel.getByText('Торги идут', { exact: true })).toBeVisible()
    const restarted = await send(`/matches/${id}/auction`)
    expect(restarted.id).not.toBe(finished.id)
    await panel.getByText('Управление аукционом', { exact: true }).click()
    await answerConfirmation(cancel, true, 'Отменить аукцион?')
    await expect(panel.getByText('Отменён', { exact: true })).toBeVisible()
  } finally {
    await cleanup(send, id)
  }
})
