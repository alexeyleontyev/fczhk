import { expect, test } from './app-test'

test('player claims the weekly freebet once and sees the leaderboard and the bank', async ({
  page,
}) => {
  await page.goto('/')
  await page.getByRole('button', { name: 'Войти игроком', exact: true }).click()
  await page
    .getByRole('navigation', { name: 'Главная навигация' })
    .getByRole('button', { name: 'Ставки', exact: true })
    .click()
  await expect(page.getByRole('heading', { name: 'Ставки', level: 1 })).toBeVisible()

  const wallet = page.getByRole('region', { name: 'Мой баланс' })
  const balance = wallet.locator('.wallet-balance strong')
  await expect(balance).toHaveText('0')
  await wallet.getByRole('button', { name: 'Забрать фрибет +100' }).click()
  await expect(balance).toHaveText('100')
  await expect(
    wallet.getByText(/Фрибет этой недели получен. Следующий — понедельник/),
  ).toBeVisible()
  await expect(wallet.getByRole('button', { name: /Забрать фрибет/ })).toHaveCount(0)

  const board = page.getByRole('region', { name: 'Лидерборд' })
  await expect(board.getByRole('row').filter({ hasText: '· вы' })).toContainText('100')
  await expect(page.getByRole('region', { name: 'Банк' })).toContainText('Принято ставок 0')

  // A second tab or a stale screen cannot take the same week's freebet twice.
  const token = await page.evaluate(() => sessionStorage.getItem('fczhk-session'))
  const again = await page.request.post('/api/wallet/freebet', {
    headers: { Authorization: `Bearer ${token}` },
  })
  expect(again.status()).toBe(409)
  await page.getByRole('button', { name: 'Обновить', exact: true }).click()
  await expect(balance).toHaveText('100')
})
