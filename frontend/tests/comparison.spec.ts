import { startPersonQuery, submit, choose } from './helpers'
import { expect, test, type Page } from '@playwright/test'

test('两人对比时间轴、证据、交换及同名独立人物', async ({ page }) => {
  await page.goto('/')
  await startPersonQuery(page)
  await expect(page.getByTestId('person-p:000002')).toBeVisible()
  await page.getByRole('button', { name: '与参考人物对比', exact: true }).click()
  await expect(page.getByTestId('compare-person-0')).toContainText('林知远')
  await expect(page.getByTestId('compare-person-1')).toContainText('周明澈')
  await expect(page.getByTestId('comparison-proof-detail')).toContainText('24 个月')
  await page.getByRole('button', { name: '时间轴', exact: true }).click()
  await expect(page.getByTestId('timeline-overlap')).toHaveCount(2)
  await expect(page.getByTestId('undated-f:000001:school')).toContainText('时间未知')
  await expect(page.locator('.career-period').filter({ hasText: '当前任职' })).toContainText(
    '2026.11',
  )
  await page.screenshot({ path: '../docs/comparison-preview.png', fullPage: true })
  await page.getByRole('button', { name: '交换对比人物', exact: true }).click()
  await submit(page)
  await expect(page.getByTestId('compare-person-0')).toContainText('周明澈')
  await expect(page.getByTestId('compare-person-1')).toContainText('林知远')
  await choose(page, 'compare-left', '林知远 · p:000001')
  await expect(page.getByRole('alert')).toContainText('请选择两位不同的人物')
  await expect(page.getByRole('status').filter({ hasText: '人物已修改' })).toBeVisible()
  await page.getByRole('button', { name: '共同经历', exact: true }).click()
  await choose(page, 'compare-right', '林知远 · p:000012')
  await expect(page.getByTestId('comparison-no-evidence')).toBeVisible()
  await expect(page.getByTestId('compare-person-0')).toContainText('p:000001')
  await expect(page.getByTestId('compare-person-1')).toContainText('p:000012')
})

test('时间未知保持独立、请求失败可重试、旧对比不覆盖新选择', async ({ page }) => {
  await page.goto('/')
  await startPersonQuery(page)
  await expect(page.getByTestId('person-p:000002')).toBeVisible()
  await page.route('**/api/v1/persons/compare', (route) =>
    route.fulfill({
      status: 503,
      contentType: 'application/json',
      body: JSON.stringify({ message: '对比测试服务不可用' }),
    }),
  )
  await page.getByRole('button', { name: '查两人关系', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText('对比测试服务不可用')
  await page.unroute('**/api/v1/persons/compare')
  await page.getByRole('button', { name: '重试对比', exact: true }).click()
  await expect(page.getByTestId('comparison-proof-detail')).toContainText('24 个月')
  let delayed = false
  await page.route('**/api/v1/persons/compare', async (route) => {
    const body = route.request().postDataJSON() as { candidate_id: string }
    if (body.candidate_id === 'p:000003') {
      delayed = true
      await new Promise((resolve) => setTimeout(resolve, 900))
    }
    try {
      await route.continue()
    } catch {
      /* 页面主动取消的旧请求。 */
    }
  })
  await choose(page, 'compare-right', '沈思宁 · p:000003')
  await expect.poll(() => delayed).toBe(true)
  await choose(page, 'compare-right', '许景行 · p:000004')
  await expect(page.getByTestId('compare-person-1')).toContainText('p:000004')
  await page.getByRole('button', { name: '时间轴', exact: true }).click()
  await expect(page.getByTestId('undated-f:000004:work')).toContainText('时间未知')
  await expect(page.getByTestId('timeline-overlap')).toHaveCount(0)
  await page.waitForTimeout(1000)
  await expect(page.getByTestId('compare-person-1')).toContainText('p:000004')
})

test('多选类别内任选、类别间同时满足、保留同条经历约束', async ({ page }) => {
  await page.goto('/')
  await startPersonQuery(page)
  await expect(page.getByTestId('person-p:000002')).toBeVisible()
  await page.getByRole('button', { name: '按条件找人', exact: true }).click()
  await submit(page)
  await choose(page, 'company-select', '星澜科技')
  await choose(page, 'role-select', '技术总监')
  await expect(page.getByTestId('person-p:000001')).toBeVisible()
  await expect(page.getByTestId('person-p:000007')).toHaveCount(0)
  await choose(page, 'company-select', '远川智能')
  await expect(page.getByTestId('person-p:000007')).toBeVisible()
  await expect(page.getByTestId('person-p:000001')).toBeVisible()
  await page.getByRole('button', { name: '查两人关系', exact: true }).click()
  await page.getByRole('button', { name: '按条件找人', exact: true }).click()
  await submit(page)
  await expect(page.getByTestId('company-select')).toContainText('星澜科技')
  await expect(page.getByTestId('company-select')).toContainText('远川智能')
  await expect(page.getByTestId('role-select')).toContainText('技术总监')
})
