import { test as base, type Page } from '@playwright/test'

export { expect } from '@playwright/test'
export type { APIRequestContext, Dialog, Locator, Page } from '@playwright/test'

// Feature suites enter through the same ready-only button as a person.
// Startup and animation suites use the base fixture to inspect the gate explicitly.
export async function autoEnterClub(page: Page) {
  const open = page
    .getByRole('button', { name: 'Открыть', exact: true })
    .and(page.locator(':enabled'))
  await page.addLocatorHandler(open, async (button) => {
    await button.click()
  })
}

export const test = base.extend({
  page: async ({ page }, use) => {
    await autoEnterClub(page)
    await use(page)
  },
})
