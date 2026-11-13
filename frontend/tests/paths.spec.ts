import { startPersonQuery, submit, choose } from './helpers'
import { expect, test, type Page } from '@playwright/test'

async function openPaths(page: Page) {
  await page.goto('/')
  await startPersonQuery(page)
  await expect(page.getByTestId('person-p:000002')).toBeVisible()
  await page.getByRole('button', { name: '与参考人物对比', exact: true }).click()
  await page.getByRole('button', { name: '经过谁连接', exact: true }).click()
  await expect(page.getByTestId('path-direct')).toBeVisible()
}

test('从对比进入路径，列表图联动、逐段证据和本段履历对比', async ({ page }) => {
  const errors: string[] = []
  page.on('pageerror', (error) => errors.push(error.message))
  await page.goto('/')
  await startPersonQuery(page)
  await expect(page.getByTestId('person-p:000002')).toBeVisible()
  await page.getByRole('button', { name: '与参考人物对比', exact: true }).click()
  await expect(page.getByTestId('comparison-proof-detail')).toContainText('24 个月')
  await page.getByRole('button', { name: '经过谁连接', exact: true }).click()
  await expect(page.getByTestId('path-direct')).toHaveAttribute('aria-pressed', 'true')
  await expect(page.getByTestId('path-proof-detail')).toContainText('24 个月')
  await choose(page, 'path-right', '程星野 · p:000008')
  await expect(page.getByTestId('path-direct')).toHaveCount(0)
  await expect(page.getByTestId('path-via-p:000007')).toHaveAttribute('aria-pressed', 'true')
  await expect(page.getByTestId('path-proof-detail')).toContainText('demo-cross-role-7')
  await expect(page.getByTestId('graph-canvas').locator('canvas').first()).toBeVisible()
  await page.getByTestId('path-segment-1').click()
  await expect(page.getByTestId('path-segment-1')).toHaveAttribute('aria-pressed', 'true')
  await expect(page.getByTestId('path-proof-detail')).toContainText('远川智能')
  await expect(page.getByTestId('path-proof-detail')).toContainText('demo-work-7')
  await expect(page.getByTestId('path-proof-detail')).toContainText('demo-work-8')
  await page.evaluate(() => window.scrollTo(0, 0))
  await page.screenshot({ path: '../docs/paths-preview.png', fullPage: true })
  await page.getByRole('button', { name: '对比本段履历', exact: true }).click()
  await expect(page.getByTestId('compare-person-0')).toContainText('p:000007')
  await expect(page.getByTestId('compare-person-1')).toContainText('p:000008')
  expect(errors).toEqual([])
})

test('同名端点保持独立，混合连接链与中间人物来源筛选', async ({ page }) => {
  await openPaths(page)
  await choose(page, 'path-right', '林知远 · p:000012')
  await expect(page.getByTestId('path-empty')).toContainText('所选范围内未发现连接链')
  await expect(page.getByTestId('path-status')).toContainText('p:000001')
  await expect(page.getByTestId('path-status')).toContainText('p:000012')
  await choose(page, 'path-relation', '全部共同经历（可混合）')
  await expect(page.getByTestId('path-via-p:000007')).toBeVisible()
  await expect(page.getByTestId('path-via-p:000036')).toBeVisible()
  await expect(page.getByTestId('path-via-p:000037')).toBeVisible()
  await choose(page, 'path-source', '仅专家库')
  await expect(page.getByTestId('path-via-p:000037')).toBeVisible()
  await expect(page.getByTestId('path-via-p:000007')).toHaveCount(0)
  await expect(page.getByTestId('path-via-p:000036')).toHaveCount(0)
  await page.getByTestId('path-segment-1').click()
  await expect(page.getByTestId('path-proof-detail')).toContainText('同校')
  await expect(page.getByTestId('path-proof-detail')).toContainText('时间未知')
  await page.setViewportSize({ width: 800, height: 1000 })
  await expect(page.getByTestId('path-via-p:000037')).toBeVisible()
  await expect(page.getByTestId('path-proof-detail')).toBeVisible()
})

test('候选受限时不能断言没有关系，连接链上限与完整空结果明确区分', async ({ page }) => {
  await openPaths(page)
  await choose(page, 'path-right', '林知远 · p:000012')
  await choose(page, 'path-relation', '全部共同经历（可混合）')
  await expect(page.getByTestId('path-via-p:000007')).toBeVisible()
  await page.locator('.path-advanced > summary').click()
  await page.getByText('搜索范围：最多一位中间人物', { exact: true }).click()
  await page.getByRole('spinbutton', { name: '中间候选上限', exact: true }).fill('1')
  await page.getByRole('spinbutton', { name: '中间候选上限', exact: true }).blur()
  await submit(page)
  await expect(page.getByTestId('path-status')).toContainText('尚不能判断是否存在连接链')
  await expect(page.getByTestId('path-status')).toContainText('中间候选数量达到上限')
  await expect(page.getByTestId('path-empty')).toContainText('搜索范围受限')
  await expect(page.getByTestId('path-empty')).not.toContainText('未发现连接链')
  await page.getByRole('spinbutton', { name: '中间候选上限', exact: true }).fill('200')
  await page.getByRole('spinbutton', { name: '中间候选上限', exact: true }).blur()
  await submit(page)
  await page.getByRole('spinbutton', { name: '间接连接链上限', exact: true }).fill('1')
  await page.getByRole('spinbutton', { name: '间接连接链上限', exact: true }).blur()
  await submit(page)
  await expect(page.getByTestId('path-status')).toContainText('连接链展示数量达到上限')
  await expect(page.getByTestId('path-via-p:000007')).toBeVisible()
  await expect(page.getByTestId('path-via-p:000036')).toHaveCount(0)
  await expect(page.getByTestId('path-empty')).toHaveCount(0)
})

test('路径请求失败可重试、主动取消与过期响应不会覆盖新端点', async ({ page }) => {
  await openPaths(page)
  await page.route('**/api/v1/relations/paths', (route) =>
    route.fulfill({
      status: 503,
      contentType: 'application/json',
      body: JSON.stringify({ message: '路径服务暂不可用' }),
    }),
  )
  await page.getByRole('button', { name: '搜索连接链', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText('路径服务暂不可用')
  await expect(page.getByTestId('path-empty')).toHaveCount(0)
  await page.unroute('**/api/v1/relations/paths')
  await page.getByRole('button', { name: '重试路径查询', exact: true }).click()
  await expect(page.getByTestId('path-direct')).toBeVisible()
  let started = false
  await page.route('**/api/v1/relations/paths', async (route) => {
    started = true
    await new Promise((resolve) => setTimeout(resolve, 900))
    try {
      await route.continue()
    } catch {
      /* 浏览器已取消旧请求。 */
    }
  })
  await page.getByRole('button', { name: '搜索连接链', exact: true }).click()
  await expect.poll(() => started).toBe(true)
  await page.getByRole('button', { name: '取消搜索', exact: true }).click()
  await expect(page.getByRole('status').filter({ hasText: '搜索已取消' })).toBeVisible()
  await page.waitForTimeout(1000)
  await expect(page.getByTestId('path-status')).toHaveCount(0)
  await expect(page.getByTestId('path-empty')).toHaveCount(0)
  await page.unroute('**/api/v1/relations/paths')
  let delayed = false
  await page.route('**/api/v1/relations/paths', async (route) => {
    const body = route.request().postDataJSON() as { candidate_id: string }
    if (body.candidate_id === 'p:000003') {
      delayed = true
      await new Promise((resolve) => setTimeout(resolve, 900))
    }
    try {
      await route.continue()
    } catch {
      /* 端点已改变。 */
    }
  })
  await choose(page, 'path-right', '沈思宁 · p:000003')
  await expect.poll(() => delayed).toBe(true)
  await choose(page, 'path-right', '程星野 · p:000008')
  await expect(page.getByTestId('path-status')).toContainText('p:000008')
  await page.waitForTimeout(1000)
  await expect(page.getByTestId('path-status')).toContainText('p:000008')
  await expect(page.getByTestId('path-via-p:000007')).toBeVisible()
  await choose(page, 'path-right', '林知远 · p:000001')
  await expect(page.getByRole('alert')).toContainText('请选择两位不同的人物')
  await expect(page.getByRole('status').filter({ hasText: '条件已修改' })).toBeVisible()
})
