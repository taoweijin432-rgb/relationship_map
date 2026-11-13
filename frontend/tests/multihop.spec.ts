import { expect, test, type Download, type Page } from '@playwright/test'
import { readFile } from 'node:fs/promises'
import { closeSaved, more, saved, startPersonQuery, submit } from './helpers'

test.skip(process.env.RELATIONSHIP_NUMERIC_BROWSER !== '1', '显式验证当前数字图多跳')

async function depth(page: Page, value: number) {
  await page.getByTestId('max-hops-select').click()
  await page
    .getByRole('option', { name: value === 1 ? '1 跳 · 直接关联' : `${value} 跳以内`, exact: true })
    .click()
  await page.keyboard.press('Escape')
}
async function downloaded(download: Download) {
  const path = await download.path()
  if (!path) throw new Error('下载文件缺失')
  return readFile(path, 'utf8')
}

test('一跳默认、修改显式提交、最短连接链及逐段图', async ({ page, request }) => {
  const meta = await (await request.get('/api/v1/meta')).json()
  expect(meta.max_relation_hops).toBe(4)
  expect(meta.graph_model).toBe('numeric-relations-v1')
  const errors: string[] = []
  page.on('pageerror', (error) => errors.push(error.message))
  await page.goto('/')
  await startPersonQuery(page)
  await expect(page.getByTestId('max-hops-select')).toContainText('1 跳')
  await expect(page.getByTestId('person-p:expert:2')).toHaveCount(0)
  await depth(page, 2)
  await expect(page.getByText('条件已修改，点击查询更新结果。下方为上次查询结果。')).toBeVisible()
  await expect(page.getByTestId('person-p:expert:2')).toHaveCount(0)
  await submit(page)
  await expect(page.getByTestId('person-p:expert:2')).toContainText('2 跳关联')
  await page.getByTestId('person-p:expert:2').click()
  const connection = page.getByTestId('connection-details')
  await expect(connection).toContainText('陈亦舟 → 林知夏 → 周景行')
  await expect(connection).toContainText('澜桥软件科技')
  await expect(connection).toContainText('远岚信息技术')
  await page.getByRole('button', { name: '查看连接图', exact: true }).click()
  await expect(connection.getByTestId('graph-canvas').locator('canvas').first()).toBeVisible()
  await expect(connection.getByTestId('graph-canvas')).toHaveAttribute('aria-busy', 'false')
  await page.screenshot({ path: test.info().outputPath('connection-desktop.png'), fullPage: true })
  await page.getByRole('tab', { name: /人物经历/ }).click()
  await expect(page.locator('.fact-card').first()).toBeVisible()
  expect(errors).toEqual([])
})

test('四跳条件保存恢复、当前页JSON与CSV、设为中心及重置', async ({ page }) => {
  await page.goto('/')
  await startPersonQuery(page)
  await depth(page, 4)
  await submit(page)
  await expect(page.locator('.query-context')).toContainText('最多 4 跳')
  await saved(page)
  await page.getByPlaceholder('为当前条件命名').fill('四跳关联')
  await page.getByRole('button', { name: '保存当前条件', exact: true }).click()
  await closeSaved(page)
  const jsonDownload = page.waitForEvent('download')
  await more(page, '导出当前页 JSON')
  const json = JSON.parse(await downloaded(await jsonDownload))
  expect(json.filters.max_hops).toBe(4)
  const person = json.items.find(
    (item: { person: { id: string } }) => item.person.id === 'p:expert:2',
  )
  expect(person.connection_detail.person_ids).toEqual(['p:expert:1', 'p:resume:1', 'p:expert:2'])
  const csvDownload = page.waitForEvent('download')
  await more(page, '导出当前页 CSV')
  const csv = await downloaded(await csvDownload)
  expect(csv).toContain('连接链分段证据')
  expect(csv).toContain('段起点人物ID')
  expect(csv).toContain('远岚信息技术')
  await page.getByRole('button', { name: '重置', exact: true }).click()
  await expect(page.getByTestId('max-hops-select')).toContainText('1 跳')
  await saved(page)
  await page.getByRole('button', { name: '恢复条件 四跳关联', exact: true }).click()
  await closeSaved(page)
  await expect(page.getByTestId('max-hops-select')).toContainText('4 跳')
  await page.getByTestId('person-p:expert:2').click()
  await expect(page.getByTestId('connection-details')).toBeVisible()
  await page.getByRole('button', { name: '以此人为中心查询', exact: true }).click()
  await expect(page.locator('.query-context')).toContainText('周景行')
  await expect(page.getByTestId('max-hops-select')).toContainText('4 跳')
})

test('手机抽屉连接链和关闭焦点', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/')
  await startPersonQuery(page)
  await depth(page, 4)
  await submit(page)
  await page.getByTestId('person-p:expert:2').click()
  const dialog = page.getByRole('dialog', { name: '人物与经历' })
  await expect.poll(async () => Math.round((await dialog.boundingBox())?.x ?? -1)).toBe(0)
  await expect(dialog.getByTestId('connection-details')).toContainText('陈亦舟 → 林知夏 → 周景行')
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  await page.screenshot({ path: test.info().outputPath('connection-mobile.png'), fullPage: true })
  await page.keyboard.press('Escape')
  await expect(dialog).toBeHidden()
  await expect(page.getByTestId('person-p:expert:2')).toBeFocused()
})

test('深度变更隔离旧响应、失败保留成功结果并可重试', async ({ page }) => {
  await page.goto('/')
  await startPersonQuery(page)
  await page.route('**/api/v1/persons/*/relations/search', async (route) => {
    if (route.request().postDataJSON().max_hops === 2) {
      const response = await route.fetch()
      await new Promise((resolve) => setTimeout(resolve, 800))
      await route.fulfill({ response })
    } else await route.continue()
  })
  await depth(page, 2)
  await submit(page)
  await depth(page, 4)
  await submit(page)
  await expect(page.locator('.query-context')).toContainText('最多 4 跳')
  await page.waitForTimeout(1000)
  await expect(page.locator('.query-context')).toContainText('最多 4 跳')
  await page.unroute('**/api/v1/persons/*/relations/search')
  await page.route('**/api/v1/persons/*/relations/search', (route) =>
    route.fulfill({
      status: 503,
      json: { code: 'GRAPH_QUERY_LIMIT', message: '多跳查询达到预算，请降低跳数或缩小范围' },
    }),
  )
  await depth(page, 3)
  await submit(page)
  await expect(page.getByRole('alert')).toContainText('多跳查询达到预算')
  await expect(page.locator('.query-context')).toContainText('最多 4 跳')
  await expect(page.getByTestId('person-p:expert:2')).toBeVisible()
  await page.unroute('**/api/v1/persons/*/relations/search')
  await submit(page)
  await expect(page.locator('.query-context')).toContainText('最多 3 跳')
})
