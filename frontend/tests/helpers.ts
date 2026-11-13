import { expect, type Page } from '@playwright/test'

export async function startPersonQuery(page: Page) {
  await page.getByTestId('reference-select').click()
  await page.getByRole('option').first().click()
  await page.keyboard.press('Escape')
  await page.getByRole('button', { name: '查关联人物', exact: true }).click()
  await expect(page.locator('.query-context')).toBeVisible()
}
export async function submit(page: Page) {
  if (await page.getByTestId('path-workspace').isVisible())
    await page.getByRole('button', { name: '搜索连接链', exact: true }).click()
  else if (await page.getByTestId('comparison-workspace').isVisible())
    await page.getByRole('button', { name: '查看关系', exact: true }).click()
  else await page.getByRole('button', { name: /^(查关联人物|查询人物)$/ }).click()
}
export async function advanced(page: Page) {
  const button = page.getByRole('button', { name: /^更多筛选/ })
  if ((await button.getAttribute('aria-expanded')) === 'false') await button.click()
}
export async function choose(page: Page, id: string, label: string) {
  const target = page.getByTestId(id)
  if (
    !(await target.isVisible()) &&
    (await page.getByRole('button', { name: /^更多筛选/ }).count())
  )
    await advanced(page)
  if (!(await target.isVisible()) && (await page.locator('.path-advanced > summary').count()))
    await page.locator('.path-advanced > summary').click()
  await target.click()
  const listId = await target.getByRole('combobox').getAttribute('aria-controls')
  if (!listId) throw new Error('筛选控件缺少选项关联')
  await page.locator(`[id="${listId}"]`).getByRole('option', { name: label, exact: true }).click()
  await page.keyboard.press('Escape')
  if (id === 'topic-kind') {
    await page.getByTestId('topic-select').click()
    const topicList = await page
      .getByTestId('topic-select')
      .getByRole('combobox')
      .getAttribute('aria-controls')
    await page.locator(`[id="${topicList}"]`).getByRole('option').first().click()
    await page.keyboard.press('Escape')
  }
  await submit(page)
}
export async function graphView(page: Page) {
  await page.getByRole('button', { name: '关系图', exact: true }).click()
  await expect(page.getByTestId('graph-canvas').locator('canvas').first()).toBeVisible()
}
export async function saved(page: Page) {
  const dialog = page.getByRole('dialog', { name: '常用条件' })
  if (!(await dialog.isVisible()))
    await page.getByRole('button', { name: '常用条件', exact: true }).click()
}
export async function closeSaved(page: Page) {
  await page
    .getByRole('dialog', { name: '常用条件' })
    .getByRole('button', { name: 'Close this dialog' })
    .click()
  await expect(page.getByRole('dialog', { name: '常用条件' })).toBeHidden()
}
export async function more(page: Page, name: string) {
  await page.getByRole('button', { name: '更多结果操作' }).click()
  await page.getByRole('menuitem', { name, exact: true }).click()
}
export async function topic(page: Page) {
  await page.getByRole('tab', { name: /人物经历/ }).click()
  await page
    .locator('.fact-card')
    .filter({ hasText: '工作经历' })
    .locator('.entity-link')
    .first()
    .click()
}
