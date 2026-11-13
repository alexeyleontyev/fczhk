import { expect, test, type Locator } from '@playwright/test'

async function frameTransforms(element: Locator) {
  return element.evaluate(
    (node) =>
      new Promise<number>((resolve) => {
        const transforms = new Set<string | null>()
        let frames = 0
        const sample = () => {
          transforms.add(node.getAttribute('transform'))
          if (++frames === 12) resolve(transforms.size)
          else requestAnimationFrame(sample)
        }
        requestAnimationFrame(sample)
      }),
  )
}

const opacity = (element: Locator) =>
  element.evaluate((node) => Number(getComputedStyle(node).opacity))

test('readiness keeps the scene playing until Open is clicked, without reopening after login', async ({
  page,
}) => {
  let releaseHealth!: () => void
  const healthGate = new Promise<void>((resolve) => {
    releaseHealth = resolve
  })
  await page.route('**/api/health', async (route) => {
    await healthGate
    await route.continue()
  })
  await page.goto('/')
  const splash = page.locator('#club-launch')
  const open = page.getByRole('button', { name: 'Открыть', exact: true })
  const ball = page.locator('.club-launch-ball')
  try {
    await expect(page.getByText('Открываем клуб…')).toBeVisible()
    await expect(open).toBeHidden()
    await expect(ball).toHaveAttribute('transform', /matrix/)
    await expect.poll(() => frameTransforms(ball)).toBeGreaterThan(1)
  } finally {
    releaseHealth()
  }

  await expect(open).toBeVisible()
  await expect(open).toBeEnabled()
  await expect(page.getByText('Клуб готов', { exact: true })).toBeVisible()
  await expect(splash).toBeVisible()
  await expect(page.locator('#root')).toBeHidden()
  await expect.poll(() => frameTransforms(ball)).toBeGreaterThan(1)

  await open.click()
  await expect(splash).toBeHidden()
  await expect(page.getByText('Локальная демонстрация')).toBeVisible()
  await page.getByRole('button', { name: 'Войти игроком', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Выходим на поле.' })).toBeVisible()
  await expect(splash).toBeHidden()
})

test('reduced motion leaves a still scene and an accessible manual entrance', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' })
  await page.goto('/')
  const open = page.getByRole('button', { name: 'Открыть', exact: true })
  await expect(open).toBeVisible()
  await expect(page.locator('#club-launch')).toBeVisible()
  await expect(page.locator('.club-launch-beer-entrance')).toBeHidden()
  expect(await frameTransforms(page.locator('.club-launch-ball'))).toBe(1)
  expect(await frameTransforms(page.locator('.club-launch-drone'))).toBe(1)
  await open.focus()
  await page.keyboard.press('Enter')
  await expect(page.locator('#club-launch')).toBeHidden()
  await expect(page.getByText('Локальная демонстрация')).toBeVisible()
})

test('a missing decorative animation bundle keeps the manual entrance usable', async ({ page }) => {
  let blocked = false
  await page.route('**/assets/launch-animation-*.js', (route) => {
    blocked = true
    return route.abort()
  })
  await page.goto('/')
  const open = page.getByRole('button', { name: 'Открыть', exact: true })
  await expect(open).toBeVisible()
  expect(blocked).toBe(true)
  await expect(page.locator('#club-launch')).toBeVisible()
  await expect(page.locator('#root')).toBeHidden()
  await expect(page.locator('.club-launch-beer-entrance')).toBeHidden()
  await expect(page.getByRole('button', { name: 'Повторить', exact: true })).toBeHidden()
  await open.click()
  await expect(page.getByText('Локальная демонстрация')).toBeVisible()
  await expect(page.locator('#club-launch')).toBeHidden()
})

test('the bottle enters from above after the third goal, unscrews and celebrates before resetting', async ({
  page,
}) => {
  const start = new Date('2026-11-13T12:00:00Z')
  await page.clock.install({ time: start })
  await page.clock.pauseAt(new Date(start.getTime() + 1000))
  await page.goto('/')
  const open = page.getByRole('button', { name: 'Открыть', exact: true })
  const entrance = page.locator('.club-launch-beer-entrance')
  const bottle = page.locator('.club-launch-bottle')
  const cap = page.locator('.club-launch-bottle-cap')
  const foam = page.locator('.club-launch-bottle-foam')
  const confetti = page.locator('.club-launch-confetti').first()
  const goal = page.locator('.club-launch-goal')
  await expect(open).toBeVisible()
  await expect(page.locator('.club-launch-ball')).toHaveAttribute('transform', /matrix/)
  await expect(entrance).toBeHidden()
  await expect(bottle).toBeHidden()
  const closedCap = await cap.getAttribute('transform')
  expect(await opacity(foam)).toBe(0)
  expect(await opacity(confetti)).toBe(0)

  // Advance browser animation frames, not an implementation-specific timeline global.
  await page.clock.runFor(1700)
  expect(await opacity(goal)).toBeGreaterThan(0)
  await expect(entrance).toBeHidden()
  expect(await opacity(foam)).toBe(0)
  await page.clock.runFor(3900)
  expect(await opacity(goal)).toBeGreaterThan(0)
  await expect(entrance).toBeHidden()
  expect(await opacity(foam)).toBe(0)
  expect(await cap.getAttribute('transform')).toBe(closedCap)
  await page.clock.runFor(3200)
  await expect(entrance).toBeHidden()
  await page.clock.runFor(450)
  expect(await opacity(goal)).toBeGreaterThan(0)
  await expect(entrance).toBeHidden()
  expect(await opacity(foam)).toBe(0)

  await page.clock.runFor(120)
  await expect(entrance).toBeVisible()
  await expect(bottle).toBeVisible()
  const entering = await entrance.boundingBox()
  expect(entering).not.toBeNull()
  expect(entering!.y).toBeLessThan(0)
  await page.clock.runFor(350)
  const descending = await entrance.boundingBox()
  expect(descending).not.toBeNull()
  expect(descending!.y).toBeGreaterThan(entering!.y)
  expect(await cap.getAttribute('transform')).toBe(closedCap)
  expect(await opacity(foam)).toBe(0)

  // The cap visibly unscrews while the bottle is still closed.
  await page.clock.runFor(1030)
  expect(await cap.getAttribute('transform')).not.toBe(closedCap)
  expect(await opacity(cap)).toBeGreaterThan(0)
  expect(await opacity(foam)).toBe(0)
  expect(await opacity(confetti)).toBe(0)
  await page.clock.runFor(750)
  expect(await opacity(foam)).toBeGreaterThan(0)
  expect(await opacity(confetti)).toBeGreaterThan(0)
  expect(await cap.getAttribute('transform')).not.toBe(closedCap)
  const confettiScene = await page.locator('.club-launch-confetti-scene').boundingBox()
  expect(confettiScene).toEqual({ x: 0, y: 0, ...page.viewportSize()! })
  const confettiTransforms = await page
    .locator('.club-launch-confetti')
    .evaluateAll((nodes) => nodes.map((node) => node.getAttribute('transform')))
  expect(
    confettiTransforms.every((transform) => transform && !/NaN|Infinity/.test(transform)),
  ).toBe(true)
  const flyingConfetti = await confetti.getAttribute('transform')
  await page.clock.runFor(100)
  expect(await confetti.getAttribute('transform')).not.toBe(flyingConfetti)

  await page.clock.runFor(3200)
  await expect(entrance).toBeHidden()
  await page.clock.runFor(9000)
  await expect(entrance).toBeHidden()
  expect(await opacity(foam)).toBe(0)
  expect(await opacity(confetti)).toBe(0)
  await page.clock.runFor(570)
  await expect(entrance).toBeVisible()
  expect(await opacity(foam)).toBe(0)
  await expect(open).toBeVisible()
  await expect(page.locator('#club-launch')).toBeVisible()

  await open.click()
  await expect(page.locator('#club-launch')).toBeHidden()
  await expect(page.getByText('Локальная демонстрация')).toBeVisible()
})

for (const width of [320, 390]) {
  test(`the bottle starts hidden and the ready button fits the ${width}px mobile screen`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: 568 })
    await page.goto('/')
    const open = page.getByRole('button', { name: 'Открыть', exact: true })
    await expect(open).toBeVisible()
    await expect(page.locator('.club-launch-bottle')).toBeHidden()
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(width)
    const button = await open.boundingBox()
    expect(button).not.toBeNull()
    expect(button!.y).toBeGreaterThanOrEqual(0)
    expect(button!.y + button!.height).toBeLessThanOrEqual(568)
  })
}
