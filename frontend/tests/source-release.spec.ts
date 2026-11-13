import { startPersonQuery, submit, choose, graphView } from './helpers'
import { expect, test, type Page } from '@playwright/test'

test.skip(process.env.RELATIONSHIP_SOURCE_RELEASE_BROWSER !== '1', '仅修正后冻结批次 B 的展示验收')

test('修正批次的旧工作关系消失，同校使用纠正目标', async ({ page, request }) => {
  const meta = await (await request.get('/api/v1/meta')).json()
  expect(meta.fact_count).toBe(118)
  await page.goto('/')
  await startPersonQuery(page)
  await expect(page.getByText('暂无匹配人物', { exact: true })).toBeVisible()
  await expect(page.getByTestId('reference-select')).toContainText('p:expert:1')
  await expect(page.getByTestId('person-p:resume:2')).toHaveCount(0)
  await expect(page.getByRole('alert')).toHaveCount(0)
  await choose(page, 'relation-select', '同校')
  await expect(page.locator('.person-row').first()).toBeVisible()
  await expect(page.getByTestId('person-p:resume:2')).toHaveCount(0)
  await expect(page.getByTestId('evidence-card').first()).toContainText('模拟标准学校2')
  await expect(page.getByTestId('evidence-card').first()).toContainText(
    'experts_education_experience:1',
  )
})

test('公司纠正与更名保留原经历定位，旧别名仍可搜索', async ({ page, request }) => {
  const aliases = await (
    await request.get('/api/v1/entities/suggest?type=organization&q=模拟标准公司2')
  ).json()
  expect(
    aliases.items.some(
      (entity: { id: string; name: string }) =>
        entity.id === '304' && entity.name === '模拟标准公司2（更名演练）',
    ),
  ).toBe(true)
  await page.goto('/')
  await startPersonQuery(page)
  await expect(page.getByText('暂无匹配人物', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: '按条件找人', exact: true }).click()
  await submit(page)
  await choose(page, 'company-select', '模拟标准公司2（更名演练）')
  await page.getByTestId('person-p:resume:7').click()
  const fact = page.locator('.fact-card').filter({ hasText: 'resume_work_experience:43' })
  await expect(fact).toContainText('模拟标准公司2（更名演练）')
  await expect(fact).toContainText('产品经理')
  await graphView(page)
})

test('旧连接链消失，图内完整无结果有明确标记', async ({ page }) => {
  const errors: string[] = []
  page.on('pageerror', (error) => errors.push(error.message))
  await page.goto('/')
  await startPersonQuery(page)
  await expect(page.getByText('暂无匹配人物', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: '查两人关系', exact: true }).click()
  await page.getByTestId('compare-right').locator('input').fill('p:resume:2')
  await page.getByRole('option').filter({ hasText: ' · p:resume:2' }).click()
  await page.keyboard.press('Escape')
  await submit(page)
  await page.getByRole('button', { name: '经过谁连接', exact: true }).click()
  const select = page.getByTestId('path-right')
  await select.click()
  await select.locator('input').fill('p:resume:8')
  await page.getByRole('option').filter({ hasText: ' · p:resume:8' }).click()
  await page.keyboard.press('Escape')
  await submit(page)
  await expect(page.getByTestId('path-empty')).toContainText('所选范围内未发现连接链')
  await expect(page.getByTestId('path-query-backend')).toContainText('图内路径计算')
  await expect(page.getByTestId('path-via-p:resume:7')).toHaveCount(0)
  await expect(page.getByRole('alert')).toHaveCount(0)
  await page.screenshot({ path: test.info().outputPath('corrected-release.png'), fullPage: true })
  expect(errors).toEqual([])
})
