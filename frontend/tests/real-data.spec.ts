import { readFile, copyFile } from 'node:fs/promises'
import { expect, test, type Page, type APIRequestContext } from '@playwright/test'
import { choose, graphView, more } from './helpers'
import { entityOptionLabel } from '../src/features/entityLabels'

test.skip(process.env.RELATIONSHIP_REAL_BROWSER !== '1', '显式验证真实数据源')

async function openRealQuery(page: Page, request: APIRequestContext, depth = 4) {
  const facts = await (await request.get('/api/v1/persons/p:expert:1076/facts')).json()
  await page.goto('/')
  await expect(page.locator('.environment-badge')).toContainText('真实数据')
  const control = page.getByTestId('reference-select')
  await control.click()
  await control.getByRole('combobox').fill(facts.person.serial_number || facts.person.name)
  await page.getByRole('option').filter({ hasText: facts.person.serial_number }).click()
  await page.keyboard.press('Escape')
  await choose(page, 'relation-select', '曾任职同一公司')
  if (depth > 1) await choose(page, 'max-hops-select', `${depth} 跳以内`)
  await expect(page.locator('.person-row')).toHaveCount(depth)
  await expect(page.getByRole('button', { name: '查关联人物', exact: true })).not.toHaveClass(
    /is-loading/,
  )
  await expect(page.getByTestId('person-p:expert:1075')).toBeVisible()
}

async function downloaded(download: import('@playwright/test').Download) {
  const path = await download.path()
  if (!path) throw new Error('下载文件缺失')
  return readFile(path, 'utf8')
}

test('真实来源标识、四跳逐段证据及画布', async ({ page, request }) => {
  const meta = await (await request.get('/api/v1/meta')).json()
  expect(meta.data_mode).toBe('real')
  expect(meta.person_count).toBe(6525)
  expect(meta.fact_count).toBe(25239)
  const errors: string[] = []
  page.on('pageerror', (error) => errors.push(error.message))
  await openRealQuery(page, request)
  await page.getByTestId('person-p:expert:1171').click()
  const details = page.getByTestId('connection-details')
  await expect(details).toContainText('4 跳')
  await page.getByRole('button', { name: '查看连接图', exact: true }).click()
  await expect(details.getByTestId('graph-canvas').locator('canvas').first()).toBeVisible()
  await expect(details.getByTestId('graph-canvas')).toHaveAttribute('aria-busy', 'false')
  await expect(page.locator('.evidence-footer')).toContainText('真实数据快照')
  await expect(page.getByText('全部人物与经历均为虚构样例')).toHaveCount(0)
  await page.screenshot({
    path: test.info().outputPath('real-four-hop-desktop.png'),
    fullPage: true,
  })
  expect(errors).toEqual([])
})

test('真实JSON、CSV和图片导出标识', async ({ page, request }) => {
  await openRealQuery(page, request)
  const jsonPending = page.waitForEvent('download')
  await more(page, '导出当前页 JSON')
  const jsonDownload = await jsonPending
  expect(jsonDownload.suggestedFilename()).toMatch(/^relationship-real-/)
  const json = JSON.parse(await downloaded(jsonDownload))
  expect(json.data_mode).toBe('real')
  expect(json.items).toHaveLength(4)
  expect(
    json.items.find((item: { person: { id: string } }) => item.person.id === 'p:expert:1171')
      .connection_detail.hop_count,
  ).toBe(4)
  const csvPending = page.waitForEvent('download')
  await more(page, '导出当前页 CSV')
  const csv = await downloaded(await csvPending)
  expect(csv).toContain('真实数据')
  expect(csv).not.toContain('模拟数据')
  await graphView(page)
  const pngPending = page.waitForEvent('download')
  await page.getByRole('button', { name: '导出图 PNG', exact: true }).click()
  const png = await pngPending
  expect(png.suggestedFilename()).toMatch(/^relationship-real-/)
  const path = await png.path()
  if (!path) throw new Error('图图片缺失')
  await copyFile(path, test.info().outputPath('real-export.png'))
  await expect(page.getByText('已导出局部图，图片含真实数据标识和范围说明')).toBeVisible()
})

test('真实公司筛选、分页及手机详情', async ({ page, request }) => {
  const entity = (await (await request.get('/api/v1/entities/company:5167')).json()).entity
  const suggested = await (
    await request.get(
      `/api/v1/entities/suggest?type=organization&q=${encodeURIComponent(entity.name)}&limit=50`,
    )
  ).json()
  const expected = await (
    await request.post('/api/v1/persons/search', { data: { organization_ids: [entity.id] } })
  ).json()
  await page.goto('/')
  await page.getByRole('button', { name: '按条件找人', exact: true }).click()
  const control = page.getByTestId('company-select')
  await control.click()
  await control.getByRole('combobox').fill(entity.name)
  await page
    .getByRole('option', { name: entityOptionLabel(entity, suggested.items), exact: true })
    .click()
  await page.keyboard.press('Escape')
  await page.getByRole('button', { name: '查询人物', exact: true }).click()
  await expect(page.getByTestId(`person-${expected.items[0].person.id}`)).toBeVisible()
  await expect(page.locator('.person-row')).toHaveCount(20)
  await page.getByRole('button', { name: '下一页', exact: true }).click()
  await expect(page.getByTestId(`person-${expected.items[0].person.id}`)).toHaveCount(0)
  await expect(page.locator('.person-row')).toHaveCount(20)
  await page.setViewportSize({ width: 390, height: 844 })
  await page.locator('.person-row').first().click()
  await expect(page.getByRole('dialog', { name: '人物与经历' })).toBeVisible()
  await expect(page.locator('.evidence-footer')).toContainText('真实数据快照')
  await page.screenshot({
    path: test.info().outputPath('real-mobile-detail.png'),
    animations: 'disabled',
  })
})
