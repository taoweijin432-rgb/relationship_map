import { expect, test } from '@playwright/test'
import { graphPositions, connectionEdgeIds } from '../src/features/graphPresentation'
import type { GraphData, EvidenceResponse, SearchResponse } from '../src/api/client'
import { graphView, startPersonQuery } from './helpers'

function pointAt(positions: ReturnType<typeof graphPositions>, id: string) {
  const point = positions.get(id)
  if (!point) throw new Error(`缺少节点坐标 ${id}`)
  return point
}

function chain(): GraphData {
  return {
    nodes: Array.from({ length: 9 }, (_, index) => ({
      id: String(index),
      label: `节点${index}`,
      type: index % 2 ? ('organization' as const) : ('person' as const),
      is_reference: index === 0,
    })),
    edges: Array.from({ length: 8 }, (_, index) => ({
      id: `edge:${index}`,
      source: String(index),
      target: String(index + 1),
      label: '任职',
      fact_id: String(index),
    })),
    truncated: false,
  }
}

test('四跳按人物连接摘要分层，重复经历、环和孤立节点布局稳定', () => {
  const data = chain()
  data.edges.push({ ...data.edges[0], id: 'parallel' })
  const positions = graphPositions(data, 900, 500, 'radial', [['0', '2', '4', '6', '8']])
  const center = pointAt(positions, '0')
  let previous = 0
  for (let index = 1; index < 9; index++) {
    const point = pointAt(positions, String(index))
    const radius = Math.hypot(point.x - center.x, point.y - center.y)
    expect(radius).toBeGreaterThan(previous)
    previous = radius
  }
  expect(graphPositions(data, 900, 500, 'radial', [['0', '2', '4', '6', '8']])).toEqual(positions)
  // 共享实体形成的画布捷径不会把摘要中的四跳人物移至一跳层。
  data.edges.push({ ...data.edges[0], id: 'cross', source: '8' })
  data.nodes.push({ id: 'isolated', label: '独立人物', type: 'person', is_reference: false })
  const withCycle = graphPositions(data, 900, 500, 'radial', [['0', '2', '4', '6', '8']])
  expect(withCycle.size).toBe(10)
  const root = pointAt(withCycle, '0')
  expect(Math.abs(pointAt(withCycle, '8').y - root.y)).toBeGreaterThan(
    Math.abs(pointAt(withCycle, '2').y - root.y),
  )
  for (const point of withCycle.values()) expect(Number.isFinite(point.x + point.y)).toBe(true)
})

test('100节点扩展环半径，为标签保留间距；路径按顺序横排', () => {
  const data = chain()
  data.nodes = Array.from({ length: 100 }, (_, index) => ({
    id: String(index),
    label: `测试人物${index}`,
    type: 'person',
    is_reference: index === 0,
  }))
  data.edges = data.nodes.slice(1).map((node) => ({
    id: `edge:${node.id}`,
    source: '0',
    target: node.id,
    fact_id: node.id,
    label: '测试连线',
  }))
  const positions = graphPositions(data, 700, 450, 'radial')
  const points = [...positions.values()]
  for (let i = 0; i < points.length; i++)
    for (let j = i + 1; j < points.length; j++)
      expect(Math.hypot(points[i].x - points[j].x, points[i].y - points[j].y)).toBeGreaterThan(110)
  const path = graphPositions(chain(), 390, 450, 'chain')
  expect([...path.values()].map((point) => point.x)).toEqual([
    60, 240, 420, 600, 780, 960, 1140, 1320, 1500,
  ])
  expect(graphPositions({ nodes: [], edges: [], truncated: false }, 390, 450, 'radial').size).toBe(
    0,
  )
})

test('接口证据生成聚焦连线，点击人物可聚焦并恢复全图', async ({ page, request }) => {
  const errors: string[] = []
  page.on('pageerror', (error) => errors.push(error.message))
  await page.goto('/')
  await startPersonQuery(page)
  await graphView(page)
  const canvas = page.getByTestId('graph-canvas')
  await expect(canvas).toHaveAttribute('data-layout', 'layered')
  await expect(canvas).toHaveAttribute('aria-busy', 'false')
  await expect(canvas).toHaveAttribute('data-edge-labels', 'on-demand')
  await expect(canvas).toHaveAttribute('data-focused-edges', '0')
  const proof: EvidenceResponse = await (
    await request.get('/api/v1/relations/evidence', {
      params: { reference_id: 'p:000001', candidate_id: 'p:000002' },
    })
  ).json()
  const edges = connectionEdgeIds(proof, '')
  expect(edges).toHaveLength(2)
  expect(edges[0]).toBe(`edge:${proof.items[0].reference.fact.id}`)
  // 相同实体的另一条经历必须通过所选证据的事实ID精确区分。
  const selected = proof.items.at(-1)
  if (!selected) throw new Error('样例缺少关系证据')
  expect(connectionEdgeIds(proof, `edge:${selected.candidate.fact.id}`)).toEqual([
    `edge:${selected.reference.fact.id}`,
    `edge:${selected.candidate.fact.id}`,
  ])
  expect(
    connectionEdgeIds(
      {
        ...proof,
        connection: {
          hop_count: 2,
          person_ids: ['a', 'b', 'c'],
          persons: [],
          segments: [],
        },
      },
      '',
    ),
  ).toEqual([])
  await page.screenshot({ path: test.info().outputPath('layered-overview.png'), fullPage: true })
  // 从实际画布的普通人物填色内取命中点，点击真实节点验证G6事件联动。
  const drawing = canvas.locator('canvas').first()
  await drawing.scrollIntoViewIfNeeded()
  const point = await canvas.evaluate((surface) => {
    for (const element of surface.querySelectorAll('canvas')) {
      const context = element.getContext('2d')
      if (!context) continue
      const pixels = context.getImageData(0, 0, element.width, element.height).data
      const bounds = element.getBoundingClientRect()
      for (let y = 0; y < element.height; y += 3)
        for (let x = 0; x < element.width; x += 3) {
          const index = (y * element.width + x) * 4
          if (pixels[index] === 229 && pixels[index + 1] === 241 && pixels[index + 2] === 237)
            return {
              x: bounds.x + (x * bounds.width) / element.width,
              y: bounds.y + (y * bounds.height) / element.height,
            }
        }
    }
    throw new Error('画布中未找到普通人物节点')
  })
  await page.mouse.click(point.x, point.y)
  await expect(canvas).not.toHaveAttribute('data-focused-edges', '0')
  await page.screenshot({ path: test.info().outputPath('layered-focus.png'), fullPage: true })
  await page.getByRole('button', { name: '查看全部关系', exact: true }).click()
  await expect(canvas).toHaveAttribute('data-focused-edges', '0')
  const download = page.waitForEvent('download')
  await page.getByRole('button', { name: '导出图 PNG', exact: true }).click()
  expect((await download).suggestedFilename()).toMatch(/\.png$/)
  expect(errors).toEqual([])
})

test('100节点密集图可缩放，桌面与手机无渲染错误', async ({ page }) => {
  const errors: string[] = []
  page.on('pageerror', (error) => errors.push(error.message))
  await page.route('**/api/v1/persons/*/relations/search', async (route) => {
    const response = await route.fetch()
    const result: SearchResponse = await response.json()
    const graph: GraphData = {
      nodes: [{ id: 'p:000001', label: '林知远', type: 'person', is_reference: true }],
      edges: [],
      truncated: false,
    }
    // 此固定样例只验证画布容量和标签，不生成业务查询结果。
    for (let index = 0; index < 9; index++) {
      const id = `layout-company:${index}`
      graph.nodes.push({
        id,
        label: `布局测试公司${index}`,
        type: 'organization',
        is_reference: false,
      })
      graph.edges.push({
        id: `root:${index}`,
        source: 'p:000001',
        target: id,
        label: '任职',
        fact_id: 'layout-only',
      })
    }
    for (let index = 0; index < 90; index++) {
      const id = `layout-person:${index}`
      graph.nodes.push({ id, label: `布局人物${index}`, type: 'person', is_reference: false })
      graph.edges.push({
        id: `person:${index}`,
        source: id,
        target: `layout-company:${index % 9}`,
        label: '任职',
        fact_id: 'layout-only',
      })
    }
    await route.fulfill({ response, json: { ...result, graph } })
  })
  await page.goto('/')
  await startPersonQuery(page)
  await graphView(page)
  await expect(page.getByTestId('graph-canvas')).toHaveAttribute('aria-busy', 'false')
  await expect(page.locator('.graph-fallback')).toHaveCount(0)
  await page.screenshot({ path: test.info().outputPath('dense-desktop.png'), fullPage: true })
  await page.getByRole('button', { name: '放大关系图', exact: true }).click()
  await page.getByRole('button', { name: '适应画布', exact: true }).click()
  await page.setViewportSize({ width: 390, height: 844 })
  await page.getByRole('button', { name: '适应画布', exact: true }).click()
  await expect(page.locator('.graph-fallback')).toHaveCount(0)
  await page.screenshot({ path: test.info().outputPath('dense-mobile.png'), fullPage: true })
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
    true,
  )
  expect(errors).toEqual([])
})
