import { readFile } from 'node:fs/promises'
import { expect, test } from '@playwright/test'
import { choose, submit, more, saved, closeSaved } from './helpers'

test.skip(process.env.RELATIONSHIP_REAL_BROWSER !== '1', '显式验证真实图同校前提')

test('同专业同校前提的勾选、保存恢复、导出与路径', async ({ page, request }) => {
  const errors: string[] = []
  page.on('pageerror', (error) => errors.push(error.message))
  const facts = await (await request.get('/api/v1/persons/p:expert:1000/facts')).json()
  await page.goto('/')
  const control = page.getByTestId('reference-select')
  await control.click()
  await control.getByRole('combobox').fill(facts.person.serial_number || facts.person.name)
  await page.getByRole('option').filter({ hasText: facts.person.serial_number }).click()
  await page.keyboard.press('Escape')
  await choose(page, 'relation-select', '同专业')
  const checkbox = page.getByTestId('same-school-required').getByRole('checkbox')
  await expect(checkbox).toBeChecked()
  await expect(page.getByTestId('person-p:expert:6590')).toBeVisible()
  await expect(page.getByTestId('person-p:expert:1031')).toHaveCount(0)
  await expect(page.locator('.query-context')).toContainText('前提 · 同校')
  await saved(page)
  await page.getByRole('textbox', { name: '条件名称', exact: true }).fill('同专业要求同校')
  await page.getByRole('button', { name: '保存当前条件', exact: true }).click()
  await closeSaved(page)
  await page.getByTestId('same-school-required').click()
  await expect(checkbox).not.toBeChecked()
  const response = page.waitForResponse(
    (r) => r.url().includes('/relations/search') && r.request().method() === 'POST',
  )
  await submit(page)
  expect((await response).request().postDataJSON().require_same_school).toBe(false)
  await saved(page)
  await page.getByRole('button', { name: '恢复条件 同专业要求同校', exact: true }).click()
  await closeSaved(page)
  await expect(checkbox).toBeChecked()
  await expect(page.getByTestId('person-p:expert:6590')).toBeVisible()
  const pending = page.waitForEvent('download')
  await more(page, '导出当前页 JSON')
  const download = await pending
  const path = await download.path()
  if (!path) throw new Error('导出文件缺失')
  const json = JSON.parse(await readFile(path, 'utf8'))
  expect(json.filters.require_same_school).toBe(true)
  expect(
    json.items.every((x: { evidence: { explanation: string }[] }) =>
      x.evidence.every((e) => e.explanation.includes('已有同校关系')),
    ),
  ).toBe(true)
  await page.screenshot({
    path: test.info().outputPath('same-major-school-desktop.png'),
    fullPage: true,
  })
  await page.getByTestId('person-p:expert:6590').click()
  await page.getByRole('button', { name: '与参考人物对比', exact: true }).click()
  await page.getByRole('button', { name: '经过谁连接', exact: true }).click()
  await choose(page, 'path-relation', '同专业')
  const pathCheck = page.getByTestId('path-same-school-required').getByRole('checkbox')
  await expect(pathCheck).toBeChecked()
  await expect(page.getByTestId('path-proof-detail')).toContainText('已有同校关系')
  await page.getByTestId('path-same-school-required').click()
  await expect(pathCheck).not.toBeChecked()
  const pathResponse = page.waitForResponse((r) => r.url().endsWith('/relations/paths'))
  await submit(page)
  expect((await pathResponse).request().postDataJSON().scope.require_same_school).toBe(false)
  await page.setViewportSize({ width: 390, height: 844 })
  await page.screenshot({
    path: test.info().outputPath('same-major-school-mobile.png'),
    fullPage: true,
  })
  expect(errors).toEqual([])
})
