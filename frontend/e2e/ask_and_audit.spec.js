// login → ask → streamed answer and sources → the auditor sees the event (START_HERE M8),
// plus the M8 done criterion: viewer, qa_user and auditor each see only their own menus.
import { expect, test } from '@playwright/test'

const PASSWORD = 'violet-lantern-orbit-42' // seeded by backend/tests/e2e_server.py
const QUESTION = 'What must happen after an OOS result?'

async function signIn(page, username) {
  await page.goto('/login')
  await page.getByLabel('Username').fill(username)
  await page.getByLabel('Password', { exact: true }).fill(PASSWORD)
  await page.getByRole('button', { name: 'Sign in' }).click()
}

async function menus(page) {
  const links = page.getByRole('navigation', { name: 'Main' }).getByRole('link')
  await expect(links.first()).toBeVisible() // wait for the signed-in shell
  return links.allInnerTexts()
}

async function signOut(page) {
  await page.getByRole('button', { name: /Vera|Quinn|Aud|Ada/ }).click()
  await page.getByRole('menuitem', { name: 'Sign out' }).click()
  await expect(page).toHaveURL(/\/login$/)
}

test('a viewer asks a question and an auditor sees it in the audit trail', async ({ page }) => {
  // the viewer: Chat, History, Documents, nothing else
  await signIn(page, 'e2e_viewer')
  await expect(page).toHaveURL(/\/$/)
  expect(await menus(page)).toEqual(['Chat', 'History', 'Documents'])

  // ask: the sources appear, then the answer streams in, then the verify notice
  await page.getByLabel('Your question').fill(QUESTION)
  await page.getByRole('button', { name: 'Send' }).click()
  const sources = page.getByRole('complementary', { name: 'Sources' })
  await expect(sources.getByTestId('source-card')).toHaveCount(2)
  await expect(sources.getByText('ACME-SOP-QC-007', { exact: true })).toBeVisible()
  await expect(sources.getByText('Fictional')).toBeVisible()
  const answer = page.getByTestId('answer')
  await expect(answer.getByTestId('answer-text')).toContainText('OOS results must be investigated')
  await expect(answer.getByText('Verify against the cited source before acting.')).toBeVisible()

  // a citation highlights its source card
  await answer.getByRole('button', { name: '[2]' }).click()
  await expect(sources.locator('#source-2')).toHaveClass(/ring-2/)

  // feedback, and the question in History
  await answer.getByRole('button', { name: 'Helpful', exact: true }).click()
  await expect(page.getByText('Feedback saved.')).toBeVisible()
  await page.getByRole('link', { name: 'History' }).click()
  await expect(page.getByRole('cell', { name: QUESTION })).toBeVisible()
  await expect(page.getByRole('cell', { name: '👍' })).toBeVisible()

  // the conversation is listed back in Chat, titled by its first question
  await page.getByRole('link', { name: 'Chat' }).click()
  await expect(page.getByRole('navigation', { name: 'Conversations' }).getByText(QUESTION)).toBeVisible()
  await signOut(page)

  // the QA user: same menus as the viewer (no Audit, no Users)
  await signIn(page, 'e2e_qa')
  await expect(page).toHaveURL(/\/$/)
  expect(await menus(page)).toEqual(['Chat', 'History', 'Documents'])
  await signOut(page)

  // the auditor lands on the audit trail, cannot chat, and sees the viewer's question
  await signIn(page, 'e2e_auditor')
  await expect(page).toHaveURL(/\/audit$/)
  expect(await menus(page)).toEqual(['Documents', 'Audit'])
  const row = page.getByRole('row').filter({ hasText: `Asked: ${QUESTION}` })
  await expect(row).toBeVisible()
  await expect(row).toContainText('e2e_viewer')
  await row.click()
  await expect(page.getByRole('dialog', { name: /Record #/ })).toContainText('OOS results must be investigated')
  await page.keyboard.press('Escape')

  // verifying the chain works and is itself recorded
  await page.getByRole('button', { name: 'Verify now' }).click()
  await expect(page.getByTestId('integrity-panel')).toContainText('Chain intact')
  await expect(page.getByRole('row').filter({ hasText: 'Integrity check: chain intact' })).toBeVisible()

  // pages outside the role redirect to the landing page
  await page.goto('/')
  await expect(page).toHaveURL(/\/audit$/)
})

test('an admin sees every menu and the user list', async ({ page }) => {
  await signIn(page, 'e2e_admin')
  expect(await menus(page)).toEqual(['Chat', 'History', 'Documents', 'Audit', 'Users'])
  await page.getByRole('link', { name: 'Users' }).click()
  await expect(page.getByTestId('user-e2e_viewer')).toContainText('Viewer')

  // a reload keeps the session: the token was only in memory, the HttpOnly cookie restores it
  await page.reload()
  await expect(page).toHaveURL(/\/admin\/users$/)
  await expect(page.getByTestId('user-e2e_admin')).toBeVisible()

  // signing out revokes the session: a reload now ends on the login page
  await signOut(page)
  await page.goto('/admin/users')
  await expect(page).toHaveURL(/\/login$/)
})
