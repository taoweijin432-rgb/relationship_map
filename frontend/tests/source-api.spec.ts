import { startPersonQuery, submit, choose, graphView, saved, closeSaved, topic } from './helpers'
import { expect, test, type Page } from '@playwright/test'

test.skip(process.env.RELATIONSHIP_SOURCE_API_BROWSER !== '1', '仅显式启用新三表原表集成验收')

async function person(page: Page, id: string, identity: string) {
  const select = page.getByTestId(id)
  await select.click()
  await select.locator('input').fill(identity)
  await page
    .getByRole('option')
    .filter({ hasText: ` · ${identity}` })
    .click()
  await page.keyboard.press('Escape')
  await submit(page)
}

test('新来源默认人物、两个入口、同名词典与同条经历筛选', async ({ page }) => {
  await page.goto('/')
  await startPersonQuery(page)
  await expect(page.getByText('模拟数据 · 本地验证')).toBeVisible()
  await page.getByText('数据与版本', { exact: true }).click()
  await expect(page.getByText(/MySQL 原表模拟源/)).toBeVisible()
  await expect(page.getByTestId('reference-select')).toContainText('p:expert:1')
  await expect(page.getByTestId('person-p:resume:2')).toBeVisible()
  await page.getByTestId('person-p:resume:2').click()
  await expect(page.getByTestId('evidence-card').first()).toContainText('24 个月')
  await expect(page.getByTestId('evidence-card').first()).toContainText('experts_work_experience:1')
  await graphView(page)
  await page.getByRole('button', { name: '按条件找人', exact: true }).click()
  await submit(page)
  await page.getByTestId('company-select').click()
  await expect(page.getByRole('option', { name: '模拟标准公司1 · 306', exact: true })).toBeVisible()
  await expect(page.getByRole('option', { name: '模拟标准公司1 · 307', exact: true })).toBeVisible()
  await page.keyboard.press('Escape')
  await choose(page, 'company-select', '模拟标准公司1 · 307')
  await choose(page, 'role-select', '技术总监')
  await expect(page.getByTestId('person-p:expert:1')).toBeVisible()
  await expect(page.getByTestId('person-p:resume:31')).toBeVisible()
  await expect(page.getByTestId('person-p:resume:7')).toHaveCount(0)
  await page.getByTestId('person-p:expert:1').click()
  await expect(page.locator('.fact-card').first()).toContainText('experts_work_experience:1')
  await page.getByRole('button', { name: '以此人为中心查询', exact: true }).click()
  await expect(page.getByTestId('reference-select')).toContainText('p:expert:1')
  await expect(page.getByTestId('person-p:resume:2')).toBeVisible()
})

test('原履历时间轴、图内连接链、逐段来源及图展示', async ({ page }) => {
  const errors: string[] = []
  page.on('pageerror', (e) => errors.push(e.message))
  await page.goto('/')
  await startPersonQuery(page)
  await page.getByTestId('person-p:resume:2').click()
  await page.getByRole('button', { name: '与参考人物对比', exact: true }).click()
  await expect(page.getByTestId('comparison-proof-detail')).toContainText('24 个月')
  await expect(page.getByTestId('comparison-proof-detail')).toContainText(
    'experts_work_experience:1',
  )
  await page.getByRole('button', { name: '时间轴', exact: true }).click()
  await expect(page.getByTestId('undated-slot:1003')).toContainText('时间未知')
  await page.getByRole('button', { name: '经过谁连接', exact: true }).click()
  await person(page, 'path-right', 'p:resume:8')
  await expect(page.getByTestId('path-via-p:resume:7')).toBeVisible()
  await expect(page.getByTestId('path-direct')).toHaveCount(0)
  await expect(page.getByTestId('path-query-backend')).toContainText('图内路径计算 · SQL 来源证据')
  await page.getByTestId('path-via-p:resume:7').click()
  await expect(page.getByTestId('path-proof-detail')).toContainText('24 个月')
  await expect(page.getByTestId('path-proof-detail')).toContainText('experts_work_experience:1')
  await page.getByTestId('path-segment-1').click()
  await expect(page.getByTestId('path-proof-detail')).toContainText('71 个月')
  await expect(page.getByTestId('path-proof-detail')).toContainText('resume_work_experience:6')
  await graphView(page)
  await page.screenshot({ path: test.info().outputPath('source-api-path.png'), fullPage: true })
  expect(errors).toEqual([])
})

test('新来源分页、专题与条件恢复', async ({ page }) => {
  await page.goto('/')
  await startPersonQuery(page)
  await expect(page.getByTestId('person-p:resume:2')).toBeVisible()
  await page.getByRole('button', { name: '按条件找人', exact: true }).click()
  await submit(page)
  await expect(page.locator('.person-row')).toHaveCount(20)
  const first = await page
    .locator('.person-row')
    .evaluateAll((rows) => rows.map((r) => r.getAttribute('data-testid')))
  await page.getByRole('button', { name: '下一页', exact: true }).click()
  await expect(page.getByText('第 2 页', { exact: true })).toBeVisible()
  await expect(page.locator('.person-row')).toHaveCount(20)
  const second = await page
    .locator('.person-row')
    .evaluateAll((rows) => rows.map((r) => r.getAttribute('data-testid')))
  expect(second.some((id) => first.includes(id))).toBe(false)
  await page.getByRole('button', { name: '上一页', exact: true }).click()
  await expect(page.getByText('第 1 页', { exact: true })).toBeVisible()
  await expect(page.locator('.person-row')).toHaveCount(20)
  await saved(page)
  await page.getByLabel('条件名称', { exact: true }).fill('原表分页验证')
  await page.getByRole('button', { name: '保存当前条件', exact: true }).click()
  await closeSaved(page)
  await topic(page)
  await expect(page.getByTestId('entity-topic-card')).toBeVisible()
  await saved(page)
  await page.getByRole('button', { name: '恢复条件 原表分页验证', exact: true }).click()
  await closeSaved(page)
  await expect(page.locator('.person-row')).toHaveCount(20)
  await expect(page.getByRole('alert')).toHaveCount(0)
})

test('图故障显示错误和重试，不显示无关系', async ({ page }) => {
  await page.goto('/')
  await startPersonQuery(page)
  await page.getByTestId('person-p:resume:2').click()
  await page.getByRole('button', { name: '与参考人物对比', exact: true }).click()
  await page.route('**/api/v1/relations/paths', (route) =>
    route.fulfill({
      status: 503,
      contentType: 'application/json',
      body: JSON.stringify({
        code: 'GRAPH_UNAVAILABLE',
        message: '图查询服务暂不可用，请稍后重试',
        data_mode: 'mock',
        data_version: 'source-api-ui-failure',
      }),
    }),
  )
  await page.getByRole('button', { name: '经过谁连接', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText('图查询服务暂不可用')
  await expect(page.getByTestId('path-empty')).toHaveCount(0)
  await page.unroute('**/api/v1/relations/paths')
  await page.getByRole('button', { name: '重试路径查询', exact: true }).click()
  await expect(page.getByTestId('path-direct')).toBeVisible()
})
