import { expect, test } from '@playwright/test'
import { startPersonQuery } from './helpers'

test('点选人物仅发一次合并详情请求，切换人物正常刷新', async ({ page }) => {
  const requests: string[] = []
  page.on('request', (request) => {
    const path = new URL(request.url()).pathname
    if (/\/(details|facts)$/.test(path) || path.endsWith('/evidence/search')) requests.push(path)
  })
  await page.goto('/')
  await startPersonQuery(page)
  await expect(page.getByTestId('evidence-card').first()).toBeVisible()
  expect(requests).toHaveLength(1)
  expect(requests[0]).toMatch(/\/details$/)
  await page.locator('.person-row').nth(1).click()
  await expect.poll(() => requests.length).toBe(2)
  expect(requests.every((path) => path.endsWith('/details'))).toBe(true)
  expect(requests[1]).not.toBe(requests[0])
  await expect(page.getByRole('alert')).toHaveCount(0)
})
