import { expect, type Locator } from '@playwright/test'

export function publicationState(match: {
  publications: { id: number; kind: string; stale: boolean }[]
}) {
  // The demo worker can advance delivery status independently of a declined action.
  return match.publications.map(({ id, kind, stale }) => ({ id, kind, stale }))
}

export async function answerConfirmation(button: Locator, accept: boolean, text: string) {
  const question = button.page().waitForEvent('dialog')
  const click = button.click()
  const dialog = await question
  expect(dialog.type()).toBe('confirm')
  expect(dialog.message()).toContain(text)
  if (accept) await dialog.accept()
  else await dialog.dismiss()
  await click
  return dialog.message()
}
