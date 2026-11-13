import { startPersonQuery } from './helpers'
import { expect, test } from '@playwright/test'

test('图内路径返回真实后端标记并展示来源证据', async ({ page, request }) => {
  test.skip(process.env.RELATIONSHIP_GRAPH_BROWSER !== '1', '显式启用图内路径工作台验证')
  const response = await request.post('/api/v1/relations/paths', {
    data: { reference_id: 'p:000001', candidate_id: 'p:000008' },
  })
  expect(response.status()).toBe(200)
  const data = await response.json()
  expect(data.query_backend).toBe('nebula')
  expect(data.projection_id).toMatch(/^relationship_lab_projection_/)
  expect(data.stats.graph_calls).toBeGreaterThan(0)
  await page.goto('/')
  await startPersonQuery(page)
  await expect(page.getByTestId('person-p:000002')).toBeVisible()
  await page.getByRole('button', { name: '与参考人物对比', exact: true }).click()
  await page.getByRole('button', { name: '经过谁连接', exact: true }).click()
  await expect(page.getByTestId('path-query-backend')).toContainText('图内路径计算')
  await expect(page.getByTestId('path-proof-detail')).toBeVisible()
  await expect(page.getByTestId('path-proof-detail')).toContainText('demo-')
})
