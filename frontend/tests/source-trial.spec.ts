import { startPersonQuery, submit, graphView, topic } from './helpers'
import { expect, test, type Page } from '@playwright/test'

test.skip(process.env.RELATIONSHIP_SOURCE_TRIAL_BROWSER !== '1', '仅显式启用本地来源样例演练')

async function choose(page: Page, id: string, name: string, entityId?: string) {
  await page.getByTestId(id).click()
  const plain = page.getByRole('option', { name, exact: true })
  if (entityId && (await plain.count()) !== 1) {
    await page.getByRole('option', { name: `${name} · ${entityId}`, exact: true }).click()
  } else await plain.click()
  await page.keyboard.press('Escape')
  await submit(page)
}

test('采样实体的两个入口、同条经历约束、图与模拟证据', async ({ page, request }) => {
  const proof = await request.get('/api/v1/persons/p:000001/facts')
  const facts = await proof.json()
  const work = facts.items.find(
    (f: { fact: { id: string } }) => f.fact.id === 'trial:f:000001:work',
  )
  expect(work).toBeTruthy()
  await page.goto('/')
  await startPersonQuery(page)
  await expect(page.getByText('模拟数据 · 本地验证')).toBeVisible()
  await expect(page.getByTestId('person-p:000002')).toContainText('模拟·')
  await expect(page.getByTestId('evidence-card').first()).toContainText('24 个月')
  await graphView(page)
  await page.getByRole('button', { name: '按条件找人', exact: true }).click()
  await submit(page)
  const suggested = await request.get('/api/v1/entities/suggest?type=organization')
  const sameNames = (await suggested.json()).items.filter(
    (entity: { name: string }) => entity.name === work.entity.name,
  )
  if (sameNames.length > 1) {
    await page.getByTestId('company-select').click()
    for (const entity of sameNames) {
      await expect(
        page.getByRole('option', { name: `${entity.name} · ${entity.id}`, exact: true }),
      ).toBeVisible()
    }
    await page.keyboard.press('Escape')
  }
  await choose(page, 'company-select', work.entity.name, work.entity.id)
  await choose(page, 'role-select', '技术总监')
  await expect(page.getByTestId('person-p:000001')).toBeVisible()
  await expect(page.getByTestId('person-p:000031')).toBeVisible()
  await expect(page.getByTestId('person-p:000007')).toHaveCount(0)
  await page.getByTestId('person-p:000001').click()
  await expect(page.locator('.fact-card').first()).toContainText('mock-raw:')
})

test('专题默认实体不能绑定旧演示ID', async ({ page, request }) => {
  const response = await request.get('/api/v1/entities/suggest?type=organization')
  const { items } = await response.json()
  expect(items[0].id).not.toBe('org:0')
  await page.goto('/')
  await startPersonQuery(page)
  await expect(page.getByTestId('person-p:000002')).toBeVisible()
  await topic(page)
  await expect(page.getByTestId('entity-topic-card')).toContainText(items[0].name)
  await expect(page.getByRole('alert')).toHaveCount(0)
})

test('对比时间轴与间接路径逐段证据', async ({ page, request }) => {
  const errors: string[] = []
  page.on('pageerror', (e) => errors.push(e.message))
  await page.goto('/')
  await startPersonQuery(page)
  await expect(page.getByTestId('person-p:000002')).toBeVisible()
  await page.getByRole('button', { name: '与参考人物对比', exact: true }).click()
  await expect(page.getByTestId('comparison-proof-detail')).toContainText('24 个月')
  await page.getByRole('button', { name: '时间轴', exact: true }).click()
  await expect(page.getByTestId('undated-trial:f:000001:school')).toContainText('时间未知')
  await page.getByRole('button', { name: '经过谁连接', exact: true }).click()
  await choose(page, 'path-right', '模拟·程星野 · p:000008')
  await expect(page.getByTestId('path-direct')).toHaveCount(0)
  await expect(page.getByTestId('path-via-p:000007')).toBeVisible()
  await page.getByTestId('path-via-p:000007').click()
  await expect(page.getByTestId('path-proof-detail')).toContainText('mock-raw:')
  await page.getByTestId('path-segment-1').click()
  await expect(page.getByTestId('path-proof-detail')).toContainText('mock-raw:')
  const response = await request.post('/api/v1/relations/paths', {
    data: { reference_id: 'p:000001', candidate_id: 'p:000008' },
  })
  const paths = await response.json()
  expect(paths.data_mode).toBe('mock')
  expect(paths.data_version).toMatch(/^(source|handoff)-trial-v1-/)
  await expect(page.getByTestId('path-query-backend')).toContainText(
    paths.query_backend === 'nebula' ? '图内路径计算' : 'SQL 查询',
  )
  await page.screenshot({ path: test.info().outputPath('source-trial.png'), fullPage: true })
  expect(errors).toEqual([])
})
