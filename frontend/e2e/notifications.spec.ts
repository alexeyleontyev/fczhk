import { expect, test } from '@playwright/test'

test('notification settings persist per-type switches and remain readable on mobile', async ({
  page,
  request,
}) => {
  const auth = await (await request.post('/api/auth/demo/admin')).json()
  const headers = { Authorization: `Bearer ${auth.token}` }
  const original = await (await request.get('/api/template', { headers })).json()
  await page.addInitScript((token) => sessionStorage.setItem('fczhk-session', token), auth.token)
  try {
    await page.goto('/')
    await page.getByRole('button', { name: 'Настройки', exact: true }).click()
    await page.getByRole('combobox', { name: 'День открытия сбора', exact: true }).selectOption('1')
    await page.getByLabel('Время открытия сбора · Москва', { exact: true }).fill('12:00')
    await page.getByRole('combobox', { name: 'День игры', exact: true }).selectOption('4')
    await page.getByLabel('Время игры · Москва', { exact: true }).fill('20:30')
    await page.getByText('Анонсы и напоминание об оплате', { exact: true }).click()
    await page.getByLabel('Чат анонсов', { exact: true }).fill('-1001111111')
    await page.getByLabel('Анонс перед открытием сбора', { exact: true }).check()
    await page.getByLabel('За сколько минут до открытия', { exact: true }).fill('15')
    await page.getByLabel('Напоминать об оплате футбола', { exact: true }).check()
    await page
      .getByRole('combobox', { name: 'День напоминания об оплате', exact: true })
      .selectOption('3')
    await page.getByLabel('Время напоминания об оплате · Москва', { exact: true }).fill('18:30')
    await page.getByText('Расширенный чат и типы сообщений', { exact: true }).click()
    await page.getByLabel('Чат расширенных уведомлений', { exact: true }).fill('-1002222222')
    await page.getByLabel('Аукцион', { exact: true }).uncheck()
    await page.getByLabel('Записи на игру', { exact: true }).check()
    await page.getByLabel('Отмены записей', { exact: true }).uncheck()
    for (const width of [320, 390, 1440]) {
      await page.setViewportSize({ width, height: 900 })
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
        true,
      )
      await page.screenshot({
        path: `test-results/notification-settings-${width}.png`,
        fullPage: true,
      })
    }
    await page.getByRole('button', { name: 'Сохранить шаблон', exact: true }).click()
    await expect(page.getByRole('status')).toHaveText('Шаблон сохранен')
    await page.reload()
    await page.getByRole('button', { name: 'Настройки', exact: true }).click()
    await page.getByText('Расширенный чат и типы сообщений', { exact: true }).click()
    await expect(page.getByLabel('Аукцион', { exact: true })).not.toBeChecked()
    await expect(page.getByLabel('Записи на игру', { exact: true })).toBeChecked()
    await expect(page.getByLabel('Отмены записей', { exact: true })).not.toBeChecked()
    const stored = await (await request.get('/api/template', { headers })).json()
    expect(stored.announcement_minutes).toBe(15)
    expect(stored.payment_reminder_time).toBe('18:30')
    expect(stored.extended_chat_id).toBe('-1002222222')
  } finally {
    const current = await (await request.get('/api/template', { headers })).json()
    await request.put('/api/template', { headers, data: { ...original, version: current.version } })
  }
})

test('collection countdown uses server time and refreshes the game when it reaches zero', async ({
  page,
  request,
}) => {
  const auth = await (await request.post('/api/auth/demo/player')).json()
  await page.addInitScript((token) => sessionStorage.setItem('fczhk-session', token), auth.token)
  await page.clock.install({ time: new Date('2040-01-01T12:00:00Z') })
  let reads = 0
  let gameReads = 0
  page.on('request', (r) => {
    if (new URL(r.url()).pathname === '/api/matches/current') gameReads++
  })
  await page.route('**/api/schedule/next', (route) => {
    reads++
    return route.fulfill({
      json: {
        server_now: '2032-06-01T11:59:55+03:00',
        opening_at: reads === 1 ? '2032-06-01T12:00:00+03:00' : null,
        starts_at: reads === 1 ? '2032-06-04T20:30:00+03:00' : null,
        location: 'Манеж',
      },
    })
  })
  await page.goto('/')
  await expect(page.getByRole('timer')).toHaveText('00:00:05')
  const before = gameReads
  await page.clock.fastForward(2000)
  await expect(page.getByRole('timer')).toHaveText('00:00:03')
  await page.clock.fastForward(3000)
  await expect(page.getByRole('timer')).toHaveCount(0)
  await expect.poll(() => gameReads).toBeGreaterThan(before)
  expect(reads).toBe(2)
})
