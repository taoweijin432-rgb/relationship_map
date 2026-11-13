import { expect, test, type Page } from '@playwright/test'
import { writeFile } from 'node:fs/promises'
import type {
  EvidenceResponse,
  FactView,
  FactsResponse,
  GraphEdge,
  SearchResponse,
} from '../src/api/client'
import { graphView, startPersonQuery } from './helpers'

async function repeatedExperienceFixture(page: Page) {
  let originalId = ''
  let sourceId = ''
  let first: FactView | undefined
  let second: FactView | undefined
  let edges: GraphEdge[] = []
  await page.route('**/api/v1/persons/*/relations/search', async (route) => {
    const response = await route.fetch()
    const data: SearchResponse = await response.json()
    sourceId = data.items[0].person.id
    const edge = data.graph.edges.find((item) => item.source === sourceId && item.label === '任职')
    if (!edge) throw new Error('演示基线缺少任职连线')
    originalId = edge.fact_id
    edges = [edge, { ...edge, id: 'edge:ui-second-tenure', fact_id: 'ui-second-tenure' }]
    data.graph = {
      ...data.graph,
      nodes: data.graph.nodes.filter((node) => node.id === edge.source || node.id === edge.target),
      edges,
    }
    await route.fulfill({ response, json: data })
  })
  await page.route('**/api/v1/persons/*/facts', async (route) => {
    const response = await route.fetch()
    const data: FactsResponse = await response.json()
    if (data.person.id === sourceId) {
      const original = data.items.find((item) => item.fact.id === originalId)
      if (!original) throw new Error('演示基线缺少连线事实')
      // 两条同公司经历仅用于UI定位回归，不重新生成业务关系。
      first = {
        ...original,
        fact: {
          ...original.fact,
          position_title: '测试第一段岗位',
          start_month: 202001,
          end_month: 202112,
          is_current: false,
        },
      }
      second = {
        ...original,
        fact: {
          ...original.fact,
          id: 'ui-second-tenure',
          position_title: '测试第二段岗位',
          start_month: 201801,
          end_month: 201912,
          is_current: false,
        },
      }
      data.items = [first, second, ...data.items.filter((item) => item.fact.id !== originalId)]
    }
    await route.fulfill({ response, json: data })
  })
  await page.route('**/api/v1/relations/evidence/search', async (route) => {
    const response = await route.fetch()
    const data: EvidenceResponse = await response.json()
    // facts与evidence并行请求，独立从当前证据构造相同的两条测试事实。
    const proof = data.items.find((item) => item.candidate.fact.id === originalId)
    if (!proof) throw new Error('演示基线缺少连线证据')
    data.items = [
      { ...proof, id: 'ui-proof-first', label: '测试第一段证据' },
      {
        ...proof,
        id: 'ui-proof-second',
        label: '测试第二段证据',
        candidate: {
          ...proof.candidate,
          fact: { ...proof.candidate.fact, id: 'ui-second-tenure' },
        },
      },
    ]
    await route.fulfill({ response, json: data })
  })
  await page.goto('/')
  await startPersonQuery(page)
  if ((page.viewportSize()?.width ?? 1600) > 800)
    await expect(page.getByTestId('evidence-card')).toHaveCount(2)
  await graphView(page)
  await expect(page.getByTestId('graph-canvas')).toHaveAttribute('aria-busy', 'false')
  return { edges, sourceId }
}

async function edgePoint(page: Page, id: string) {
  const canvas = page.getByTestId('graph-canvas').locator('canvas').first()
  await canvas.scrollIntoViewIfNeeded()
  const bounds = await canvas.boundingBox()
  if (!bounds) throw new Error('关系图画布不可见')
  // 两节点固定样例的连线位于画布中心，沿曲线区域寻找真实命中点。
  for (const ratio of [0.5, 0.45, 0.55]) {
    for (let offset = -100; offset <= 100; offset += 5) {
      const point = { x: bounds.x + bounds.width / 2 + offset, y: bounds.y + bounds.height * ratio }
      await page.mouse.move(point.x, point.y)
      const tooltip = page.locator('.graph-edge-tooltip')
      if ((await tooltip.count()) && (await tooltip.getAttribute('data-edge-id')) === id)
        return point
    }
  }
  throw new Error(`未找到连线的真实画布命中点 ${id}`)
}

test('边标签开关、悬停时间和同公司多经历精确定位', async ({ page }) => {
  const errors: string[] = []
  let factRequests = 0
  page.on('request', (request) => {
    if (new URL(request.url()).pathname.endsWith('/facts')) factRequests++
  })
  page.on('pageerror', (error) => errors.push(error.message))
  const { edges } = await repeatedExperienceFixture(page)
  const point = await edgePoint(page, edges[1].id)
  await expect(page.getByRole('tooltip')).toContainText('测试第二段岗位')
  await expect(page.getByRole('tooltip')).toContainText('2018.01 — 2019.12')
  const loadedRequests = factRequests
  await edgePoint(page, edges[0].id)
  await expect(page.getByRole('tooltip')).toContainText('测试第一段岗位')
  expect(factRequests).toBe(loadedRequests)
  await page.mouse.click(point.x, point.y)
  const selected = page.getByTestId('selected-edge-detail')
  await expect(selected).toContainText('测试第二段岗位')
  await expect(selected).toContainText('任职')
  await expect(page.getByTestId('evidence-card')).toHaveCount(1)
  await expect(page.getByTestId('evidence-card')).toContainText('测试第二段证据')
  await selected.getByText('这条连线的来源').click()
  await expect(selected).toContainText('ui-second-tenure')
  await page.getByRole('tab', { name: /人物经历/ }).click()
  await expect(page.locator('.selected-fact')).toContainText('测试第二段岗位')
  const canvas = page.getByTestId('graph-canvas').locator('canvas').first()
  await page.getByRole('button', { name: '放大关系图', exact: true }).click()
  const before = await canvas.screenshot()
  await writeFile(test.info().outputPath('labels-before.png'), before)
  const toggle = page.getByRole('checkbox', { name: '显示全部关系文字' })
  await expect(toggle).not.toBeChecked()
  await expect(page.getByTestId('graph-canvas')).toHaveAttribute('data-edge-labels', 'on-demand')
  await page.getByText('显示全部关系文字', { exact: true }).click()
  await expect(toggle).toBeChecked()
  await expect(page.getByTestId('graph-canvas')).toHaveAttribute('data-edge-labels', 'visible')
  expect((await canvas.screenshot()).equals(before)).toBe(false)
  await page.getByText('显示全部关系文字', { exact: true }).click()
  await expect(toggle).not.toBeChecked()
  await writeFile(test.info().outputPath('labels-restored.png'), await canvas.screenshot())
  await expect.poll(async () => (await canvas.screenshot()).equals(before)).toBe(true)
  await page.screenshot({ path: test.info().outputPath('selected-edge.png'), fullPage: true })
  expect(errors).toEqual([])
})

test('悬停失败后可以点击读取详情，详情失败重试保留连线定位', async ({ page }) => {
  const { edges, sourceId } = await repeatedExperienceFixture(page)
  let failed = true
  await page.route(`**/api/v1/persons/${encodeURIComponent(sourceId)}/facts`, async (route) => {
    if (failed)
      await route.fulfill({
        status: 503,
        contentType: 'application/json',
        body: JSON.stringify({ message: '测试经历暂不可用' }),
      })
    else await route.fallback()
  })
  const point = await edgePoint(page, edges[1].id)
  await expect(page.getByRole('tooltip')).toContainText('测试经历暂不可用')
  await page.mouse.click(point.x, point.y)
  await expect(page.getByRole('alert')).toContainText('测试经历暂不可用')
  failed = false
  await page.getByRole('button', { name: '重新加载详情', exact: true }).click()
  await expect(page.getByTestId('selected-edge-detail')).toContainText('测试第二段岗位')
  await expect(page.getByTestId('evidence-card')).toHaveCount(1)
})

test('悬停及点击拒绝混用新版本事实', async ({ page }) => {
  const { edges, sourceId } = await repeatedExperienceFixture(page)
  await page.route(`**/api/v1/persons/${encodeURIComponent(sourceId)}/facts`, async (route) => {
    const response = await route.fetch()
    const data: FactsResponse = await response.json()
    await route.fulfill({ response, json: { ...data, data_version: 'ui-new-version' } })
  })
  const point = await edgePoint(page, edges[0].id)
  await expect(page.getByRole('tooltip')).toContainText('版本不一致')
  await page.mouse.click(point.x, point.y)
  await expect(page.getByRole('alert')).toContainText('版本不一致')
  await expect(page.getByTestId('selected-edge-detail')).toHaveCount(0)
})

test.describe('窄屏点选连线', () => {
  test.use({ viewport: { width: 390, height: 844 }, hasTouch: true })
  test('触摸连线在抽屉展示对应经历', async ({ page }) => {
    const { edges } = await repeatedExperienceFixture(page)
    const point = await edgePoint(page, edges[1].id)
    await page.touchscreen.tap(point.x, point.y)
    await expect(page.getByRole('dialog', { name: '人物与经历' })).toBeVisible()
    await expect(page.getByRole('dialog', { name: '人物与经历' })).toHaveCSS('transform', 'none')
    await expect(page.getByTestId('selected-edge-detail')).toContainText('测试第二段岗位')
    await expect(page.getByTestId('selected-edge-detail')).toBeInViewport()
    await expect(page.getByTestId('evidence-card')).toHaveCount(1)
    await page.screenshot({
      path: test.info().outputPath('mobile-selected-edge.png'),
    })
  })
})
