import { startPersonQuery, submit, choose, graphView } from './helpers'
import { expect, test, type Page } from '@playwright/test'
import { spawnSync } from 'node:child_process'

test('人物查询、证据、设为中心与关系图', async ({ page }) => {
  const errors: string[] = []
  page.on('pageerror', (error) => errors.push(error.message))
  await page.goto('/')
  await startPersonQuery(page)
  await expect(page.getByText('模拟数据 · 本地验证')).toBeVisible()
  await expect(page.getByTestId('person-p:000002')).toBeVisible()
  await graphView(page)
  await expect(page.getByTestId('evidence-card').first()).toContainText('24 个月')
  await page.screenshot({ path: '../docs/prototype-preview.png', fullPage: true })
  await page.getByRole('button', { name: '展开关联人物', exact: true }).click()
  await expect(page.getByRole('status').filter({ hasText: /已加入|本次仅|这些直接/ })).toBeVisible()
  await page.getByRole('button', { name: '以此人为中心查询', exact: true }).first().click()
  await expect(page.locator('.query-context')).toContainText('周明澈')
  await expect(page.locator('.graph-fallback')).toHaveCount(0)
  expect(errors).toEqual([])
})

test('组合条件同条经历、翻页、状态保留与空结果', async ({ page }) => {
  await page.goto('/')
  await startPersonQuery(page)
  await expect(page.getByTestId('person-p:000002')).toBeVisible()
  await page.getByRole('button', { name: '按条件找人', exact: true }).click()
  await submit(page)
  await expect(page.getByTestId('person-p:000001')).toBeVisible()
  await page.getByRole('button', { name: '下一页', exact: true }).click()
  await expect(page.locator('.list-pagination')).toContainText('第 2 页')
  await expect(page.getByTestId('person-p:000022')).toBeVisible()
  await choose(page, 'company-select', '星澜科技')
  await choose(page, 'role-select', '技术总监')
  await expect(page.getByTestId('person-p:000001')).toBeVisible()
  await expect(page.getByTestId('person-p:000007')).toHaveCount(0)
  await expect(page.locator('.list-pagination')).toContainText('第 1 页')
  await page.getByRole('button', { name: '找关联的人', exact: true }).click()
  await submit(page)
  await expect(page.getByTestId('person-p:000002')).toBeVisible()
  await page.getByRole('button', { name: '按条件找人', exact: true }).click()
  await submit(page)
  await expect(page.getByTestId('company-select')).toContainText('星澜科技')
  await choose(page, 'school-select', '青岚大学')
  await expect(page.getByText('暂无匹配人物', { exact: true })).toBeVisible()
})

test('失败请求明确提示并可重试', async ({ page }) => {
  await page.goto('/')
  await startPersonQuery(page)
  await expect(page.getByTestId('person-p:000002')).toBeVisible()
  await page.route('**/api/v1/persons/*/relations/search', (route) =>
    route.fulfill({
      status: 503,
      contentType: 'application/json',
      body: JSON.stringify({ message: '测试服务暂不可用' }),
    }),
  )
  await page.getByRole('button', { name: '刷新查询', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText('测试服务暂不可用')
  await expect(page.getByText('暂无匹配人物', { exact: true })).toHaveCount(0)
  await page.unroute('**/api/v1/persons/*/relations/search')
  await page.getByRole('button', { name: '重新查询', exact: true }).click()
  await expect(page.getByTestId('person-p:000002')).toBeVisible()
})

test('过期请求不能覆盖新的筛选条件', async ({ page }) => {
  await page.goto('/')
  await startPersonQuery(page)
  await expect(page.getByTestId('person-p:000002')).toBeVisible()
  await page.route('**/api/v1/persons/search', async (route) => {
    const payload = route.request().postDataJSON() as { organization_ids?: string[] }
    if (payload.organization_ids?.includes('org:0'))
      await new Promise((resolve) => setTimeout(resolve, 900))
    try {
      await route.continue()
    } catch {
      /* 浏览器主动取消的旧请求无需继续。 */
    }
  })
  await page.getByRole('button', { name: '按条件找人', exact: true }).click()
  await submit(page)
  await choose(page, 'company-select', '星澜科技')
  await page.waitForTimeout(350)
  await choose(page, 'company-select', '星澜科技')
  await choose(page, 'company-select', '远川智能')
  await expect(page.getByTestId('person-p:000007')).toBeVisible()
  await expect(page.getByTestId('person-p:000001')).toHaveCount(0)
  await page.waitForTimeout(1000)
  await expect(page.getByTestId('person-p:000001')).toHaveCount(0)
})

test('重复启动明确报告端口占用且保留正在运行的服务', async ({ request }) => {
  const attempt = spawnSync('bash', ['../scripts/dev.sh'], {
    cwd: process.cwd(),
    encoding: 'utf8',
    timeout: 5000,
  })
  expect(attempt.status).toBe(1)
  expect(attempt.stderr).toContain(`端口 ${process.env.RELATIONSHIP_API_PORT || 8000} 已被占用`)
  const health = await request.get('/api/v1/health')
  expect(health.status()).toBe(200)
})
