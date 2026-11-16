import { expect, test } from '@playwright/test'
import { readFile } from 'node:fs/promises'
import { startPersonQuery, advanced, saved, closeSaved, graphView } from './helpers'
import { experienceGroups } from '../src/features/experienceGroups'
import type { PersonDetailsResponse, FactsResponse, FactView } from '../src/api/client'

test('初始等待选人，编辑保留结果，分页保存导出受控，重置恢复初始', async ({ page }) => {
  const searches: string[] = []
  page.on('request', (request) => {
    if (request.url().endsWith('/relations/search')) searches.push(request.postData() ?? '')
  })
  await page.goto('/')
  await expect(page.getByRole('heading', { name: '先选择你想查的人' })).toBeVisible()
  expect(searches).toHaveLength(0)
  await startPersonQuery(page)
  await expect(page.getByTestId('evidence-card').first()).toBeVisible()
  const firstResult = await page.locator('.person-row').first().getAttribute('data-testid')
  const count = searches.length
  await page.getByTestId('relation-select').click()
  await page.getByRole('option', { name: '同校', exact: true }).click()
  await page.keyboard.press('Escape')
  await expect(page.getByRole('status').filter({ hasText: '条件已修改' })).toBeVisible()
  expect(searches).toHaveLength(count)
  await expect(page.locator('.person-row').first()).toHaveAttribute(
    'data-testid',
    firstResult ?? '',
  )
  await expect(page.getByTestId('evidence-card').first()).toContainText('同公司同期')
  await expect(page.getByRole('button', { name: '下一页', exact: true })).toBeDisabled()
  await saved(page)
  await expect(page.getByRole('button', { name: '保存当前条件', exact: true })).toBeDisabled()
  await closeSaved(page)
  await page.getByRole('button', { name: '更多结果操作' }).click()
  await expect(page.getByRole('menuitem', { name: '导出当前页 CSV' })).toHaveAttribute(
    'aria-disabled',
    'true',
  )
  await page.keyboard.press('Escape')
  await page.getByRole('button', { name: '查关联人物', exact: true }).click()
  await expect(page.locator('.query-context')).toContainText('同校')
  await expect(page.getByTestId('evidence-card').first()).toContainText('同校')
  await page.getByRole('button', { name: '重置', exact: true }).click()
  await expect(page.getByRole('heading', { name: '先选择你想查的人' })).toBeVisible()
  await expect(page.getByTestId('reference-select')).toContainText('搜索姓名')
  await expect(page.getByTestId('relation-select')).toContainText('同公司同期')
})

test('时间和来源进入完整条件摘要，移除标签等待提交', async ({ page }) => {
  await page.goto('/')
  await startPersonQuery(page)
  await page.getByRole('button', { name: '按条件找人', exact: true }).click()
  await advanced(page)
  await page.getByRole('combobox', { name: '任职开始月', exact: true }).fill('2020-01')
  await page.keyboard.press('Enter')
  await page.getByTestId('source-select').click()
  await page.getByRole('option', { name: '仅专家库', exact: true }).click()
  await page.keyboard.press('Escape')
  await page.getByRole('button', { name: '查询人物', exact: true }).click()
  await expect(page.locator('.query-context')).toContainText('2020-01')
  await expect(page.locator('.query-context')).toContainText('专家库')
  await expect(page.locator('.query-context')).toContainText('2 项条件')
  await page.locator('.el-tag').filter({ hasText: '来源' }).getByRole('button').click()
  await expect(page.getByRole('status').filter({ hasText: '条件已修改' })).toBeVisible()
})

test('同条教育以来源键归组，缺键和不同人物独立', async ({ request }) => {
  const data: FactsResponse = await (await request.get('/api/v1/persons/p:000001/facts')).json()
  const school = data.items.find((view) => view.fact.type === 'education')
  if (!school) throw new Error('演示基线缺少学校事实')
  const left: FactView = {
    ...school,
    fact: { ...school.fact, experience_key: 'expert:education:1' },
  }
  const major: FactView = {
    ...school,
    entity: { ...school.entity, type: 'major', name: '测试专业' },
    fact: { ...left.fact, id: 'test-major', type: 'major' },
  }
  expect(experienceGroups([left, major])).toHaveLength(1)
  expect(experienceGroups([left, major])[0].views).toHaveLength(2)
  expect(
    experienceGroups([left, { ...major, fact: { ...major.fact, person_id: 'other-person' } }]),
  ).toHaveLength(2)
  expect(
    experienceGroups([left, { ...major, fact: { ...major.fact, experience_key: null } }]),
  ).toHaveLength(2)
  expect(
    experienceGroups([
      left,
      { ...major, fact: { ...major.fact, experience_key: 'resume:education:1' } },
    ]),
  ).toHaveLength(2)
})

for (const viewport of [
  { width: 1600, height: 1000 },
  { width: 1366, height: 768 },
  { width: 1024, height: 768 },
  { width: 390, height: 844 },
]) {
  test(`${viewport.width}×${viewport.height} 布局、图控件和详情可达`, async ({ page }) => {
    await page.setViewportSize(viewport)
    const errors: string[] = []
    page.on('pageerror', (error) => errors.push(error.message))
    await page.goto('/')
    await startPersonQuery(page)
    await expect(page.getByTestId('graph-canvas')).toHaveCount(0)
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),
    ).toBe(true)
    if (viewport.width <= 800) {
      await expect(page.getByRole('dialog', { name: '人物与经历' })).toBeHidden()
      await page.locator('.person-row').first().click()
      await expect(page.getByRole('dialog', { name: '人物与经历' })).toBeVisible()
      await expect(page.getByTestId('evidence-card').first()).toBeVisible()
      await page.keyboard.press('Escape')
      await expect(page.getByRole('dialog', { name: '人物与经历' })).toBeHidden()
      await expect(page.locator('.person-row').first()).toBeFocused()
    } else await expect(page.getByTestId('evidence-card').first()).toBeVisible()
    await page.screenshot({
      path: test.info().outputPath(`people-${viewport.width}.png`),
      fullPage: true,
    })
    await graphView(page)
    await page.getByRole('button', { name: '放大关系图', exact: true }).click()
    await page.getByRole('button', { name: '缩小关系图', exact: true }).click()
    await page.getByRole('button', { name: '适应画布', exact: true }).click()
    await expect(page.getByRole('button', { name: '全屏关系图' })).toBeVisible()
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),
    ).toBe(true)
    await page.screenshot({
      path: test.info().outputPath(`workbench-${viewport.width}.png`),
      fullPage: true,
    })
    expect(errors).toEqual([])
  })
}

for (const viewport of [
  { width: 1600, height: 1000 },
  { width: 1366, height: 768 },
  { width: 1024, height: 768 },
  { width: 390, height: 844 },
]) {
  test(`${viewport.width}×${viewport.height} 长证据和履历在面板内滚动`, async ({ page }) => {
    await page.setViewportSize(viewport)
    // 仅扩充界面测试响应，确保两种页签均有超长内容。
    await page.route('**/api/v1/persons/*/details', async (route) => {
      const response = await route.fetch()
      const data: PersonDetailsResponse = await response.json()
      const proof = data.evidence?.[0]
      const view = data.facts[0]
      if (!proof || !view) throw new Error('演示基线缺少经历或共同证据')
      data.evidence = Array.from({ length: 32 }, (_, index) => ({
        ...proof,
        id: `scroll-proof-${index}`,
        explanation: `滚动测试证据 ${index + 1}`,
      }))
      data.facts = Array.from({ length: 32 }, (_, index) => ({
        ...view,
        fact: { ...view.fact, id: `scroll-fact-${index}`, experience_key: null },
      }))
      await route.fulfill({ response, json: data })
    })
    await page.goto('/')
    await startPersonQuery(page)
    if (viewport.width <= 800) await page.locator('.person-row').first().click()
    const panel = page.getByRole('complementary', { name: '证据详情' })
    const content = panel.getByRole('region', { name: '人物与证据内容' })
    await expect(content).toBeVisible()
    await expect(panel.getByTestId('evidence-card')).toHaveCount(32)
    const panelHeight = await panel.evaluate((element) => element.getBoundingClientRect().height)
    expect(panelHeight).toBeLessThanOrEqual(viewport.height)
    await expect
      .poll(() => content.evaluate((element) => element.scrollHeight - element.clientHeight))
      .toBeGreaterThan(1000)
    await content.focus()
    const before = await page.evaluate(() => ({
      pageY: window.scrollY,
      pageHeight: document.documentElement.scrollHeight,
      headerY: document.querySelector('.evidence-panel .panel-header')?.getBoundingClientRect().y,
      footerY: document.querySelector('.evidence-footer')?.getBoundingClientRect().y,
    }))
    await content.press('End')
    await expect.poll(() => content.evaluate((element) => element.scrollTop)).toBeGreaterThan(1000)
    await expect(panel.getByTestId('evidence-card').last()).toBeInViewport()
    expect(await page.evaluate(() => window.scrollY)).toBe(before.pageY)
    expect(
      await panel.locator('.panel-header').evaluate((element) => element.getBoundingClientRect().y),
    ).toBe(before.headerY)
    expect(
      await panel
        .locator('.evidence-footer')
        .evaluate((element) => element.getBoundingClientRect().y),
    ).toBe(before.footerY)
    await panel.getByRole('tab', { name: /人物经历/ }).click()
    await expect(panel.getByTestId('experience-group')).toHaveCount(32)
    await content.focus()
    await content.press('End')
    await expect(panel.getByTestId('experience-group').last()).toBeInViewport()
    expect(await page.evaluate(() => document.documentElement.scrollHeight)).toBe(before.pageHeight)
    expect(await panel.evaluate((element) => element.getBoundingClientRect().height)).toBe(
      panelHeight,
    )
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),
    ).toBe(true)
    await page.screenshot({ path: test.info().outputPath('detail-scroll.png'), fullPage: true })
  })
}

test('连接链按需加载，修改两人后需要提交，重复人物明确报错', async ({ page }) => {
  let pathCalls = 0
  page.on('request', (request) => {
    if (request.url().endsWith('/relations/paths')) pathCalls++
  })
  await page.goto('/')
  await startPersonQuery(page)
  await page.getByRole('button', { name: '与参考人物对比', exact: true }).click()
  await expect(page.getByTestId('comparison-proof-detail')).toBeVisible()
  expect(pathCalls).toBe(0)
  await page.getByRole('button', { name: '经过谁连接', exact: true }).click()
  await expect(page.getByTestId('path-status')).toBeVisible()
  expect(pathCalls).toBe(1)
  await page.getByRole('button', { name: '共同经历', exact: true }).click()
  await page.getByTestId('compare-right').click()
  await page.getByRole('option', { name: '林知远 · p:000001', exact: true }).click()
  await page.keyboard.press('Escape')
  await expect(page.getByRole('status').filter({ hasText: '人物已修改' })).toBeVisible()
  await expect(page.getByRole('button', { name: '经过谁连接', exact: true })).toBeDisabled()
  await page.getByRole('button', { name: '查看关系', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText('请选择两位不同的人物')
})

test('翻页请求失败保留成功页码与人物，再次翻页可恢复', async ({ page }) => {
  await page.goto('/')
  await page.getByRole('button', { name: '按条件找人', exact: true }).click()
  await page.getByRole('button', { name: '查询人物', exact: true }).click()
  await expect(page.locator('.list-pagination')).toContainText('第 1 页')
  const original = await page.locator('.person-row').first().getAttribute('data-testid')
  await page.route('**/api/v1/persons/search', (route) =>
    route.fulfill({
      status: 503,
      contentType: 'application/json',
      body: JSON.stringify({ message: '分页查询暂不可用' }),
    }),
  )
  await page.getByRole('button', { name: '下一页', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText('分页查询暂不可用')
  await expect(page.locator('.list-pagination')).toContainText('第 1 页')
  await expect(page.locator('.person-row').first()).toHaveAttribute('data-testid', original ?? '')
  await page.unroute('**/api/v1/persons/search')
  await page.getByRole('button', { name: '下一页', exact: true }).click()
  await expect(page.locator('.list-pagination')).toContainText('第 2 页')
})

test('键盘选择人物和提交查询，详情页签可以键盘切换', async ({ page }) => {
  await page.goto('/')
  const reference = page.getByTestId('reference-select').getByRole('combobox')
  await reference.press('ArrowDown')
  await expect(page.getByRole('option').first()).toBeVisible()
  await reference.press('ArrowDown')
  await reference.press('Enter')
  await reference.press('Escape')
  const query = page.getByRole('button', { name: '查关联人物', exact: true })
  await expect(query).toBeEnabled()
  await query.focus()
  await page.keyboard.press('Enter')
  await expect(page.getByTestId('evidence-card').first()).toBeVisible()
  await page.getByRole('tab', { name: /人物经历/ }).focus()
  await page.keyboard.press('Enter')
  await expect(page.getByTestId('experience-group').first()).toBeVisible()
  await page.getByRole('tab', { name: /共同经历/ }).press('Enter')
  await expect(page.getByTestId('evidence-card').first()).toBeVisible()
  await graphView(page)
  await page.getByRole('button', { name: '全屏关系图' }).click()
  await expect.poll(() => page.evaluate(() => !!document.fullscreenElement)).toBe(true)
  await page.keyboard.press('Escape')
  await expect.poll(() => page.evaluate(() => !!document.fullscreenElement)).toBe(false)
})

test('旧版 schemaVersion 1 条件原样恢复并重新校验版本', async ({ page }) => {
  const legacy = JSON.parse(
    await readFile(new URL('./fixtures/saved-query-v1.json', import.meta.url), 'utf8'),
  )
  await page.addInitScript((value) => {
    localStorage.setItem('relationship-query.saved.v1', JSON.stringify(value))
  }, legacy)
  await page.goto('/')
  await saved(page)
  await page.getByRole('button', { name: '恢复条件 旧版人物条件', exact: true }).click()
  await expect(page.getByRole('dialog', { name: '常用条件' }).getByRole('status')).toContainText(
    '数据版本已变化',
  )
  await closeSaved(page)
  await expect(page.getByTestId('person-p:000002')).toBeVisible()
  await expect(page.locator('.list-pagination')).toContainText('第 1 页')
})
