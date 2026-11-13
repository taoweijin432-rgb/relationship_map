import {
  startPersonQuery,
  submit,
  choose,
  graphView,
  saved,
  closeSaved,
  more,
  topic,
} from './helpers'
import { expect, test, type Page, type Download } from '@playwright/test'
import { readFile } from 'node:fs/promises'

async function downloaded(download: Download) {
  const path = await download.path()
  if (!path) throw new Error('下载文件不存在')
  return readFile(path)
}

test('缺少 randomUUID 时仍能保存条件并在刷新后恢复', async ({ page }) => {
  await page.addInitScript(() => {
    Object.defineProperty(window.crypto, 'randomUUID', { configurable: true, value: undefined })
  })
  await page.goto('/')
  await startPersonQuery(page)
  await expect(page.getByTestId('person-p:000002')).toBeVisible()
  await saved(page)
  await page.getByRole('textbox', { name: '条件名称', exact: true }).fill('HTTP常用条件')
  await page.getByRole('button', { name: '保存当前条件', exact: true }).click()
  await expect(
    page.getByRole('button', { name: '恢复条件 HTTP常用条件', exact: true }),
  ).toBeVisible()
  const stored = await page.evaluate(() =>
    JSON.parse(localStorage.getItem('relationship-query.saved.v1') ?? 'null'),
  )
  expect(stored.schemaVersion).toBe(1)
  expect(stored.entries[0].id).toMatch(/^[0-9a-f]{32}$/)
  await closeSaved(page)
  await page.reload()
  await saved(page)
  await page.getByRole('button', { name: '恢复条件 HTTP常用条件', exact: true }).click()
  await closeSaved(page)
  await expect(page.getByTestId('person-p:000002')).toBeVisible()
})

test('公司学校专题、来源履历、保存专题与发起对比', async ({ page }) => {
  const errors: string[] = []
  page.on('pageerror', (error) => errors.push(error.message))
  await page.goto('/')
  await startPersonQuery(page)
  await expect(page.getByTestId('person-p:000002')).toBeVisible()
  await topic(page)
  await expect(page.getByTestId('entity-topic-card')).toContainText('星澜科技有限公司')
  await expect(page.getByTestId('person-p:000001')).toBeVisible()
  await choose(page, 'role-select', '技术总监')
  await expect(page.getByTestId('person-p:000007')).toHaveCount(0)
  await expect(page.locator('.fact-card').first()).toContainText('demo-repeat-1')
  await saved(page)
  await page.getByRole('textbox', { name: '条件名称', exact: true }).fill('星澜总监专题')
  await page.getByRole('button', { name: '保存当前条件', exact: true }).click()
  await closeSaved(page)
  await saved(page)
  await expect(
    page.getByRole('button', { name: '恢复条件 星澜总监专题', exact: true }),
  ).toBeVisible()
  await page.evaluate(() => window.scrollTo(0, 0))
  await page.waitForTimeout(100)
  await page.screenshot({ path: '../docs/entity-topic-preview.png', fullPage: true })
  await closeSaved(page)
  await page.getByRole('button', { name: '找关联的人', exact: true }).click()
  await submit(page)
  await expect(page.getByTestId('person-p:000002')).toBeVisible()
  await saved(page)
  await page.getByRole('button', { name: '恢复条件 星澜总监专题', exact: true }).click()
  await closeSaved(page)
  await expect(page.getByTestId('entity-topic-card')).toContainText('星澜科技')
  await expect(page.getByTestId('role-select')).toContainText('技术总监')
  await choose(page, 'topic-kind', '学校')
  await expect(page.getByTestId('entity-topic-card')).toContainText('江城大学')
  await expect(page.getByTestId('person-p:000001')).toBeVisible()
  await expect(page.getByTestId('person-p:000002')).toBeVisible()
  await page.getByTestId('person-p:000002').click()
  await page.getByRole('button', { name: '查两人关系', exact: true }).click()
  await choose(page, 'compare-left', '林知远 · p:000001')
  await expect(page.getByTestId('compare-person-1')).toContainText('p:000002')
  expect(errors).toEqual([])
})

test('共同时间窗与月数约束证据，切换同校清除任职限制', async ({ page }) => {
  await page.goto('/')
  await startPersonQuery(page)
  await expect(page.getByTestId('evidence-card').first()).toContainText('24 个月')
  await choose(page, 'relation-company-select', '星澜科技')
  await page.getByRole('combobox', { name: '共同任职开始月', exact: true }).fill('2021-01')
  await page.keyboard.press('Enter')
  await page.getByRole('combobox', { name: '共同任职结束月', exact: true }).fill('2021-12')
  await page.keyboard.press('Enter')
  await page.getByTestId('minimum-months').getByRole('spinbutton').fill('12')
  await page.getByTestId('minimum-months').getByRole('spinbutton').blur()
  await submit(page)
  await expect(page.getByTestId('person-p:000002')).toBeVisible()
  await expect(page.getByTestId('evidence-card').first()).toContainText('12 个月')
  await expect(page.getByTestId('evidence-card').first()).toContainText('2021.01 — 2021.12')
  const promise = page.waitForEvent('download')
  await more(page, '导出当前页 JSON')
  const data = JSON.parse((await downloaded(await promise)).toString())
  expect(data.filters.min_overlap_months).toBe(12)
  expect(
    data.items.find((item: { person: { id: string } }) => item.person.id === 'p:000002').evidence[0]
      .overlap_months,
  ).toBe(12)
  await page.getByTestId('minimum-months').getByRole('spinbutton').fill('13')
  await page.getByTestId('minimum-months').getByRole('spinbutton').blur()
  await submit(page)
  await expect(page.getByText('暂无匹配人物', { exact: true })).toBeVisible()
  await choose(page, 'relation-select', '同校')
  await expect(page.getByTestId('person-p:000002')).toBeVisible()
  await expect(page.getByTestId('evidence-card').first()).toContainText('同校')
  await expect(page.getByTestId('minimum-months')).toBeHidden()
})

test('保存分页查询仅保留条件，刷新与版本变化后从第一页重查', async ({ page }) => {
  await page.goto('/')
  await startPersonQuery(page)
  await expect(page.getByTestId('person-p:000002')).toBeVisible()
  await page.getByRole('button', { name: '按条件找人', exact: true }).click()
  await submit(page)
  await expect(page.getByTestId('person-p:000001')).toBeVisible()
  await page.getByRole('button', { name: '下一页', exact: true }).click()
  await expect(page.getByTestId('person-p:000022')).toBeVisible()
  await saved(page)
  await page.getByRole('textbox', { name: '条件名称', exact: true }).fill('全部人物')
  await page.getByRole('button', { name: '保存当前条件', exact: true }).click()
  await closeSaved(page)
  const stored = await page.evaluate(() => {
    const key = 'relationship-query.saved.v1'
    const data = JSON.parse(localStorage.getItem(key) ?? '{}')
    data.entries[0].query.dataVersion = 'older-demo-version'
    localStorage.setItem(key, JSON.stringify(data))
    return data
  })
  expect(stored.entries[0].query.filters.cursor).toBeUndefined()
  expect(stored.entries[0].query.mode).toBe('entity')
  expect(stored.entries[0].query.items).toBeUndefined()
  await page.reload()
  await startPersonQuery(page)
  await expect(page.getByTestId('person-p:000002')).toBeVisible()
  await saved(page)
  await page.getByRole('button', { name: '恢复条件 全部人物', exact: true }).click()
  await closeSaved(page)
  await expect(page.getByTestId('person-p:000001')).toBeVisible()
  await expect(page.locator('.list-pagination')).toContainText('第 1 页')
  await expect(page.getByRole('status').filter({ hasText: '数据版本已变化' })).toBeVisible()
  await saved(page)
  await page.getByRole('button', { name: '删除条件 全部人物', exact: true }).click()
  await saved(page)
  await expect(page.getByRole('button', { name: '恢复条件 全部人物', exact: true })).toHaveCount(0)
})

test('当前页导出、CSV 文本保护与带范围标记的图图片', async ({ page }) => {
  await page.goto('/')
  await startPersonQuery(page)
  await expect(page.getByTestId('person-p:000002')).toBeVisible()
  await page.getByRole('button', { name: '按条件找人', exact: true }).click()
  await submit(page)
  await expect(page.getByTestId('person-p:000001')).toBeVisible()
  await page.getByRole('button', { name: '下一页', exact: true }).click()
  await expect(page.getByTestId('person-p:000022')).toBeVisible()
  const pending = page.waitForEvent('download')
  await more(page, '导出当前页 JSON')
  const data = JSON.parse((await downloaded(await pending)).toString())
  expect(data.scope).toBe('current_page')
  expect(data.data_mode).toBe('mock')
  expect(data.has_more).toBe(true)
  expect(data.items).toHaveLength(20)
  expect(data.items[0].person.id).toBe('p:000022')
  expect(data.items[0].facts[0].fact.source_record_id).toBeTruthy()
  await page.route('**/api/v1/exports/persons', async (route) => {
    const response = await route.fetch()
    const json = await response.json()
    json.items[0].person.name = '=SUM(1,2)'
    json.items[0].facts[0].fact.source_record_id = '+dangerous-cell'
    await route.fulfill({ response, json })
  })
  const csvPending = page.waitForEvent('download')
  await more(page, '导出当前页 CSV')
  const csv = (await downloaded(await csvPending)).toString('utf8')
  expect(csv).toContain('仅当前页')
  expect(csv).toContain('人物全部有效履历')
  expect(csv).toContain('"\'=SUM(1,2)"')
  expect(csv).toContain('"\'+dangerous-cell"')
  const pngPending = page.waitForEvent('download')
  await graphView(page)
  await page.getByRole('button', { name: '导出图 PNG', exact: true }).click()
  const png = await pngPending
  const bytes = await downloaded(png)
  expect(bytes.subarray(0, 8).toString('hex')).toBe('89504e470d0a1a0a')
  expect(bytes.length).toBeGreaterThan(1000)
  await png.saveAs('../docs/graph-export-preview.png')
})

test('导出错误可重试，过期导出在条件变化后不得下载', async ({ page }) => {
  await page.goto('/')
  await startPersonQuery(page)
  await expect(page.getByTestId('person-p:000002')).toBeVisible()
  await page.route('**/api/v1/exports/persons', (route) =>
    route.fulfill({
      status: 409,
      contentType: 'application/json',
      body: JSON.stringify({ message: '数据版本已变化，请重新查询后导出' }),
    }),
  )
  await more(page, '导出当前页 JSON')
  await expect(page.getByRole('alert')).toContainText('导出失败：数据版本已变化')
  await page.unroute('**/api/v1/exports/persons')
  let started = false
  const downloads: Download[] = []
  page.on('download', (download) => downloads.push(download))
  await page.route('**/api/v1/exports/persons', async (route) => {
    started = true
    await new Promise((resolve) => setTimeout(resolve, 900))
    try {
      await route.continue()
    } catch {
      /* 筛选变化后主动取消。 */
    }
  })
  await more(page, '导出当前页 JSON')
  await expect.poll(() => started).toBe(true)
  await choose(page, 'relation-select', '同校')
  await expect(page.getByTestId('evidence-card').first()).toContainText('同校')
  await page.waitForTimeout(1000)
  expect(downloads).toHaveLength(0)
  await page.unroute('**/api/v1/exports/persons')
  const pending = page.waitForEvent('download')
  await more(page, '导出当前页 JSON')
  expect((await pending).suggestedFilename()).toMatch(/\.json$/)
})

test('损坏保存记录不会被自动覆盖，浏览器拒绝写入时明确报错', async ({ page }) => {
  await page.goto('/')
  await startPersonQuery(page)
  await page.evaluate(() => localStorage.setItem('relationship-query.saved.v1', 'broken-record'))
  await page.reload()
  await startPersonQuery(page)
  await expect(page.getByTestId('person-p:000002')).toBeVisible()
  await saved(page)
  await expect(page.getByRole('button', { name: '清空损坏记录', exact: true })).toBeVisible()
  expect(await page.evaluate(() => localStorage.getItem('relationship-query.saved.v1'))).toBe(
    'broken-record',
  )
  await page.getByRole('button', { name: '清空损坏记录', exact: true }).click()
  await page.evaluate(() => {
    Storage.prototype.setItem = () => {
      throw new DOMException('blocked', 'QuotaExceededError')
    }
  })
  await saved(page)
  await page.getByRole('textbox', { name: '条件名称', exact: true }).fill('存储失败')
  await page.getByRole('button', { name: '保存当前条件', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText('浏览器无法保存条件')
  await saved(page)
  await expect(page.getByRole('button', { name: '恢复条件 存储失败', exact: true })).toHaveCount(0)
})
