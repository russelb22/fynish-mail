import { expect, test } from '@playwright/test'

async function refreshQueue(page: import('@playwright/test').Page) {
  await page.getByRole('button', { name: 'Refresh Mail Accounts' }).click()
  await expect(page.locator('.message-row').first()).toBeVisible()
}

async function enableMockAccounts(page: import('@playwright/test').Page) {
  await page.getByRole('button', { name: 'Settings' }).click()
  await page.getByLabel('Show mock accounts in the app').check()
  await page.getByRole('button', { name: 'Review Queue' }).click()
}

test.describe.configure({ mode: 'serial' })

test('review queue loads mocked accounts and compact empty category chips', async ({
  page,
}) => {
  await page.goto('/')
  await enableMockAccounts(page)
  await refreshQueue(page)

  await expect(page.getByRole('heading', { name: 'Review Queue' })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'family@example.net' })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'personal@example.com' })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'work@example.com' })).toBeVisible()
  await expect(page.locator('.empty-group-chip').first()).toBeVisible()
})

test('spam rescue renders read-only mock candidates', async ({ page }) => {
  await page.goto('/')
  await enableMockAccounts(page)
  await refreshQueue(page)

  await page.getByRole('button', { name: 'Spam Rescue' }).click()

  await expect(page.getByRole('heading', { name: 'Spam Rescue' })).toBeVisible()
  await expect(page.locator('.spam-rescue-row').filter({ hasText: 'Invoice receipt for utility service' })).toBeVisible()
  await expect(page.locator('.spam-rescue-row').filter({ hasText: 'Final notice: claim your reward today' })).toHaveCount(0)
  await expect(page.getByRole('button', { name: /Restore/i })).toHaveCount(0)
})

test('keyboard shortcuts stage and undo the next queue message', async ({
  page,
}) => {
  await page.goto('/')
  await enableMockAccounts(page)
  await refreshQueue(page)

  const firstSubject = (await page.locator('.message-row .subject-line strong').first().textContent()) ?? ''
  expect(firstSubject).not.toBe('')

  await page.keyboard.press('1')

  await expect(page.getByText('1 change staged')).toBeVisible()
  await expect(page.locator('.staged-queue-item').filter({ hasText: firstSubject })).toBeVisible()
  await expect(page.locator('.summary-stat').filter({ hasText: 'Staged' }).locator('strong')).toHaveText('1')

  await page.keyboard.press('u')

  await expect(page.getByText('1 change staged')).toHaveCount(0)
  await expect(page.locator('.message-row .subject-line strong').filter({ hasText: firstSubject })).toBeVisible()
  await expect(page.locator('.summary-stat').filter({ hasText: 'Staged' }).locator('strong')).toHaveText('0')
})

test('staged toolbar can discard all staged changes', async ({ page }) => {
  await page.goto('/')
  await enableMockAccounts(page)
  await refreshQueue(page)

  await page.keyboard.press('2')
  await page.keyboard.press('3')

  await expect(page.getByText('2 changes staged')).toBeVisible()
  await page.getByRole('button', { name: 'Discard' }).click()
  await expect(page.getByText('Discarded 2 staged changes.')).toBeVisible()
  await expect(page.locator('.summary-stat').filter({ hasText: 'Staged' }).locator('strong')).toHaveText('0')
})

test('commit shortcut commits staged changes', async ({ page }) => {
  await page.goto('/')
  await enableMockAccounts(page)
  await refreshQueue(page)

  await page.keyboard.press('1')
  await expect(page.getByText('1 change staged')).toBeVisible()

  await page.keyboard.press('c')

  await expect(page.getByText('Committed 1 change.')).toBeVisible()
  await expect(page.locator('.summary-stat').filter({ hasText: 'Staged' }).locator('strong')).toHaveText('0')
})

test('refresh clears stale commit row errors', async ({ page }) => {
  await page.goto('/')
  await enableMockAccounts(page)
  await refreshQueue(page)

  await page.route('**/api/review-queue/staged-actions/commit', async (route) => {
    const body = route.request().postDataJSON() as {
      actions: Array<{ action: string; client_action_id: string | null; message_id: number }>
    }
    const action = body.actions[0]
    await route.fulfill({
      contentType: 'application/json',
      body: JSON.stringify({
        committed_count: 0,
        failed_count: 1,
        results: [
          {
            client_action_id: action.client_action_id,
            message_id: action.message_id,
            action: action.action,
            status: 'stale',
            code: 'stale_message',
            message: 'This message changed after the queue loaded. Review it again.',
            executed: false,
            labels_added: [],
            labels_removed: [],
          },
        ],
      }),
    })
  })

  await page.keyboard.press('1')
  await expect(page.getByText('1 change staged')).toBeVisible()
  await page.keyboard.press('c')

  await expect(page.getByText('This message changed after the queue loaded. Review it again.')).toBeVisible()

  await page.getByRole('button', { name: 'Refresh Mail Accounts' }).click()

  await expect(page.getByText('This message changed after the queue loaded. Review it again.')).toHaveCount(0)
})

test('scroll-to-top control appears on long workflow pages only', async ({
  page,
}) => {
  await page.setViewportSize({ width: 900, height: 520 })
  await page.goto('/')
  await enableMockAccounts(page)
  await refreshQueue(page)

  const scrollTopButton = page.getByRole('button', { name: 'Scroll to top' })
  await expect(scrollTopButton).toHaveCount(0)

  await page.evaluate(() => window.scrollTo(0, 600))
  await expect(scrollTopButton).toBeVisible()

  await scrollTopButton.click()
  await expect
    .poll(() => page.evaluate(() => window.scrollY), { timeout: 3000 })
    .toBeLessThan(20)
  await expect(scrollTopButton).toHaveCount(0)

  await page.getByRole('button', { name: 'Settings' }).click()
  await page.evaluate(() => window.scrollTo(0, 600))
  await expect(scrollTopButton).toHaveCount(0)
})
