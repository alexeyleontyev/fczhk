import { test, expect } from '@playwright/test'

test('mobile admin: create, enroll, payment, finalize, teams and publish', async ({ page }) => {
  await page.goto('/')
  await page.getByRole('button', { name: 'Войти администратором' }).click()
  await expect(page.getByRole('heading', { name: 'Выходим на поле.' })).toBeVisible()
  await page.screenshot({ path: 'test-results/mobile-game.png', fullPage: true })
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)

  await page.getByRole('button', { name: 'Новая игра' }).click()
  // A separate future date makes the scenario repeatable without touching the seeded match.
  const unique = new Date(
    Date.now() + 3650 * 86400000 + Math.floor(Math.random() * 5000) * 86400000,
  )
  const local = unique.toISOString().slice(0, 10) + 'T20:00'
  await page.getByLabel('Дата и время · Москва').fill(local)
  await page.getByLabel('Место игры').fill('Тестовый манеж MVP')
  await page.getByLabel('Стоимость, ₽', { exact: true }).fill('800')
  await page.getByLabel('Куда переводить').fill('Тест: без перевода')
  await page.getByRole('button', { name: 'Создать черновик' }).click()
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await page.getByRole('button', { name: 'Открыть сбор', exact: true }).click()
  await expect(page.getByText('Запись открыта', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Записаться полевым' }).click()
  await expect(page.getByText('Вы записаны полевым', { exact: true }).first()).toBeVisible()
  await page.getByRole('button', { name: 'Подтвердить оплату: Алексей', exact: true }).click()
  await expect(
    page.getByRole('button', { name: 'Снять оплату: Алексей', exact: true }),
  ).toBeVisible()

  await page.getByRole('button', { name: 'Добавить', exact: true }).click()
  await page.getByRole('combobox', { name: 'Игрок', exact: true }).selectOption({ label: 'Михаил' })
  await page.getByRole('button', { name: 'Добавить в состав', exact: true }).click()
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await page.getByRole('button', { name: 'Финализировать сбор', exact: true }).click()
  await page
    .getByRole('dialog')
    .getByRole('button', { name: 'Финализировать сбор', exact: true })
    .click()
  await expect(page.getByText('Сбор завершен', { exact: true })).toBeVisible()
  await page.getByLabel('Команда: Алексей', { exact: true }).selectOption('white')
  await expect(page.getByLabel('Команда: Михаил', { exact: true })).toBeEnabled()
  await page.getByLabel('Команда: Михаил', { exact: true }).selectOption('black')
  await expect(page.getByRole('button', { name: 'Утвердить команды' })).toBeEnabled()
  await page.getByRole('button', { name: 'Утвердить команды' }).click()
  await expect(page.getByText('Команды готовы', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Поменять цвета команд' }).click()
  await expect(page.getByLabel('Команда: Алексей', { exact: true })).toHaveValue('black')
  await expect(page.getByLabel('Команда: Михаил', { exact: true })).toHaveValue('white')
  await expect(page.getByText('Команды готовы', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Опубликовать составы' }).click()
  await expect(
    page.getByRole('status').filter({ hasText: 'Публикация поставлена в очередь' }),
  ).toBeVisible()
  await page.screenshot({ path: 'test-results/mobile-teams.png', fullPage: true })
})

test('player has no administrative controls; membership profile and archive work', async ({
  page,
}) => {
  await page.goto('/')
  await page.getByRole('button', { name: 'Войти игроком', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Выходим на поле.' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Новая игра' })).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Настройки', exact: true })).toHaveCount(0)
  await page.getByRole('button', { name: 'Игроки', exact: true }).click()
  await page.getByLabel('Поиск игроков').fill('Михаил')
  await expect(page.getByRole('heading', { name: 'Михаил', exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Профиль', exact: true }).click()
  await expect(page.getByLabel('Игровой alias')).toHaveValue('Михаил')
  await page.getByRole('button', { name: 'Архив', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Все игры' })).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
})

test('desktop layout and template editing', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1050 })
  await page.goto('/')
  await page.getByRole('button', { name: 'Войти администратором' }).click()
  await expect(page.getByRole('heading', { name: 'Выходим на поле.' })).toBeVisible()
  await page.screenshot({ path: 'test-results/desktop-game.png', fullPage: true })
  await page.getByRole('button', { name: 'Настройки', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Расписание и шаблон' })).toBeVisible()
  await page.getByRole('combobox', { name: 'День открытия сбора', exact: true }).selectOption('6')
  await page.getByLabel('Время открытия сбора · Москва', { exact: true }).fill('23:45')
  await page.getByRole('combobox', { name: 'День игры', exact: true }).selectOption('0')
  await page.getByLabel('Время игры · Москва', { exact: true }).fill('20:30')
  await page.getByRole('button', { name: 'Сохранить шаблон' }).click()
  await expect(page.getByRole('status')).toHaveText('Шаблон сохранен')
  await page.reload()
  await page.getByRole('button', { name: 'Настройки', exact: true }).click()
  await expect(
    page.getByRole('combobox', { name: 'День открытия сбора', exact: true }),
  ).toHaveValue('6')
  await expect(page.getByLabel('Время открытия сбора · Москва', { exact: true })).toHaveValue(
    '23:45',
  )
  await expect(page.getByRole('combobox', { name: 'День игры', exact: true })).toHaveValue('0')
  await expect(page.getByLabel('Время игры · Москва', { exact: true })).toHaveValue('20:30')
  await page.screenshot({ path: 'test-results/configurable-schedule-desktop.png', fullPage: true })
  await page.setViewportSize({ width: 390, height: 844 })
  await page
    .getByRole('heading', { name: 'Расписание и шаблон', exact: true })
    .scrollIntoViewIfNeeded()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  await page.screenshot({ path: 'test-results/configurable-schedule-mobile.png', fullPage: false })
})
