import { answerConfirmation } from './confirmation-helpers'
import { expect, test } from '@playwright/test'

const red = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAACgAAAAeCAIAAADRv8uKAAAAQUlEQVR4nO3QwQ0AMAyDwJT9d07fXoB8zAIn8XZu4sidwlp4VFZYC4/KCmvhUVlhLTwqK6yFR2WFtfCorLDW2eoP10YBO0pqtFEAAAAASUVORK5CYII=',
  'base64',
)
const blue = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAACgAAAAeCAIAAADRv8uKAAAAQklEQVR4nO3QwQ0AIADCQGT/nfUrC5QPXeCSHumqkSuqBoOZxP4GY5mjssFY5qhsMJY5KhuMZY7KBmOZo7LBWLXVD9VIATvNW+V3AAAAAElFTkSuQmCC',
  'base64',
)

test('admin saves a private opening photo before any player joins, replaces and removes it', async ({
  page,
  request,
}) => {
  const admin = await (await request.post('/api/auth/demo/admin')).json()
  const player = await (await request.post('/api/auth/demo/player')).json()
  const headers = { Authorization: `Bearer ${admin.token}` }
  const memberHeaders = { Authorization: `Bearer ${player.token}` }
  const original = await (await request.get('/api/template', { headers })).json()
  const weekday = (new Date(Date.now() + 3 * 3600000).getUTCDay() + 6) % 7
  let id: number | null = null
  try {
    expect(
      (
        await request.put('/api/template', {
          headers,
          data: {
            ...original,
            enabled: true,
            opening_weekday: (weekday + 1) % 7,
            opening_time: '12:00',
            game_weekday: (weekday + 4) % 7,
            start_time: '20:00',
            location: 'Манеж с картинкой',
          },
        })
      ).ok(),
    ).toBe(true)
    await page.addInitScript((token) => sessionStorage.setItem('fczhk-session', token), admin.token)
    await page.route('**/api/matches/current', (route) => route.fulfill({ json: null }))
    await page.goto('/')
    const input = page.getByLabel('Выбрать картинку к посту', { exact: true })
    await expect(
      page.getByRole('button', { name: 'Записать игроков заранее', exact: true }),
    ).toBeVisible()
    await input.setInputFiles({ name: 'opening.png', mimeType: 'image/png', buffer: red })
    await expect(page.getByRole('button', { name: 'Заменить картинку', exact: true })).toBeVisible()
    id = Number(new URL(page.url()).searchParams.get('game'))
    expect(id).toBeGreaterThan(0)
    const saved = await (await request.get(`/api/matches/${id}`, { headers })).json()
    expect(saved.registrations).toHaveLength(0)
    expect(saved.publications).toHaveLength(0)
    expect(saved.status).toBe('draft')
    expect(saved.collection_image.mime_type).toBe('image/png')
    const preview = page.getByAltText('Предпросмотр картинки к посту открытия сбора')
    await expect(preview).toBeVisible()
    await expect.poll(() => preview.evaluate((img: HTMLImageElement) => img.naturalWidth)).toBe(40)
    expect(
      (
        await request.get(`/api/matches/${id}/collection-image`, { headers: memberHeaders })
      ).status(),
    ).toBe(403)
    await page.reload()
    await expect(preview).toBeVisible()
    await expect.poll(() => preview.evaluate((img: HTMLImageElement) => img.naturalWidth)).toBe(40)
    for (const width of [320, 390, 1440]) {
      await page.setViewportSize({ width, height: 900 })
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
        true,
      )
      await page.screenshot({ path: `test-results/collection-image-${width}.png`, fullPage: true })
    }
    await input.setInputFiles({ name: 'replacement.png', mimeType: 'image/png', buffer: blue })
    await expect
      .poll(
        async () =>
          (await (await request.get(`/api/matches/${id}`, { headers })).json()).collection_image.id,
      )
      .not.toBe(saved.collection_image.id)
    await expect(page.getByRole('button', { name: 'Убрать из поста', exact: true })).toBeEnabled()
    await page.getByRole('button', { name: 'Убрать из поста', exact: true }).click()
    await expect(preview).toHaveCount(0)
    await expect(page.getByRole('button', { name: 'Добавить картинку', exact: true })).toBeEnabled()
    expect(
      (await (await request.get(`/api/matches/${id}`, { headers })).json()).collection_image,
    ).toBeNull()
    await input.setInputFiles({ name: 'opening.png', mimeType: 'image/png', buffer: red })
    await expect(page.getByRole('button', { name: 'Заменить картинку', exact: true })).toBeEnabled()
    await answerConfirmation(
      page.getByRole('button', { name: 'Открыть сбор', exact: true }),
      true,
      'Пост с картинкой',
    )
    await expect(page.getByRole('button', { name: 'Утвердить составы', exact: true })).toBeVisible()
    await expect(input).toHaveCount(0)
    const opened = await (await request.get(`/api/matches/${id}`, { headers })).json()
    expect(opened.publications).toHaveLength(1)
    expect(opened.collection_image.id).toBe(saved.collection_image.id)
  } finally {
    if (id) {
      const match = await (await request.get(`/api/matches/${id}`, { headers })).json()
      await request.post(`/api/matches/${id}/cancel`, {
        headers,
        data: { version: match.version, reason: 'Завершение проверки картинки' },
      })
    }
    const current = await (await request.get('/api/template', { headers })).json()
    await request.put('/api/template', { headers, data: { ...original, version: current.version } })
  }
})
