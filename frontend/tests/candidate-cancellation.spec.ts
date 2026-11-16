import { expect, test, type Page, type Route } from '@playwright/test'
import { startPersonQuery } from './helpers'

declare global {
  interface Window {
    __candidateAborts?: string[]
  }
}

async function observeAbortSignals(page: Page) {
  await page.addInitScript(() => {
    const aborted: string[] = []
    Object.defineProperty(window, '__candidateAborts', { value: aborted })
    const original = window.fetch.bind(window)
    window.fetch = (input, init) => {
      init?.signal?.addEventListener('abort', () => aborted.push(String(input)), { once: true })
      return original(input, init)
    }
  })
}

async function holdOldCandidate(page: Page, pattern: string, keyword: string) {
  let release: () => void = () => undefined
  const gate = new Promise<void>((resolve) => (release = resolve))
  await page.route(pattern, async (route: Route) => {
    if (new URL(route.request().url()).searchParams.get('q') === keyword) await gate
    try {
      await route.continue()
    } catch {
      // 已主动取消的旧请求不能再继续发送。
    }
  })
  return release
}

async function expectAborted(page: Page, keyword: string) {
  await expect
    .poll(() =>
      page.evaluate((text) => {
        return (
          window.__candidateAborts?.some(
            (url) => new URL(url, location.href).searchParams.get('q') === text,
          ) ?? false
        )
      }, keyword),
    )
    .toBe(true)
}

test('人物新关键词取消旧请求，最新候选仍可选择', async ({ page }) => {
  const old = '取消候选旧词'
  await observeAbortSignals(page)
  const release = await holdOldCandidate(page, '**/api/v1/persons/suggest?**', old)
  try {
    await page.goto('/')
    const input = page.getByTestId('reference-select').getByRole('combobox')
    await input.click()
    const requested = page.waitForRequest((r) => new URL(r.url()).searchParams.get('q') === old)
    await input.fill(old)
    await requested
    await input.fill('周明澈')
    await expectAborted(page, old)
    await expect(page.getByRole('option').filter({ hasText: '周明澈' }).first()).toBeVisible()
    await expect(page.getByRole('alert')).toHaveCount(0)
  } finally {
    release()
  }
})

test('学校和公司等实体请求按类别取消，旧响应不覆盖新候选', async ({ page }) => {
  const old = '取消公司旧词'
  await observeAbortSignals(page)
  const release = await holdOldCandidate(page, '**/api/v1/entities/suggest?**', old)
  try {
    await page.goto('/')
    await page.getByRole('button', { name: '按条件找人', exact: true }).click()
    const input = page.getByTestId('company-select').getByRole('combobox')
    await page.getByTestId('company-select').click()
    const requested = page.waitForRequest((r) => new URL(r.url()).searchParams.get('q') === old)
    await input.fill(old)
    await requested
    await input.fill('星澜')
    await expectAborted(page, old)
    await expect(page.getByRole('option').filter({ hasText: '星澜科技' }).first()).toBeVisible()
    await expect(page.getByRole('alert')).toHaveCount(0)
  } finally {
    release()
  }
})

test('离开两人对比会取消该页面的候选请求', async ({ page }) => {
  const old = '取消对比旧词'
  await observeAbortSignals(page)
  const release = await holdOldCandidate(page, '**/api/v1/persons/suggest?**', old)
  try {
    await page.goto('/')
    await startPersonQuery(page)
    await expect(page.getByTestId('person-p:000002')).toBeVisible()
    await page.getByRole('button', { name: '与参考人物对比', exact: true }).click()
    const input = page.getByTestId('compare-left').getByRole('combobox')
    await input.click()
    const requested = page.waitForRequest((r) => new URL(r.url()).searchParams.get('q') === old)
    await input.fill(old)
    await requested
    await page.keyboard.press('Escape')
    await page.getByRole('button', { name: '返回找人', exact: true }).click()
    await expectAborted(page, old)
    await expect(page.getByTestId('reference-select')).toBeVisible()
    await expect(page.getByRole('alert')).toHaveCount(0)
  } finally {
    release()
  }
})

test('初始化候选被新输入替换后，初始化仍完成且最新候选不被覆盖', async ({ page }) => {
  await observeAbortSignals(page)
  const release = await holdOldCandidate(page, '**/api/v1/persons/suggest?**', '')
  const initial = page.waitForRequest(
    (request) =>
      request.url().includes('/persons/suggest?') &&
      new URL(request.url()).searchParams.get('q') === '',
  )
  try {
    await page.goto('/')
    await initial
    const input = page.getByTestId('reference-select').getByRole('combobox')
    await input.click()
    await input.fill('周明澈')
    await expectAborted(page, '')
    const person = page.getByRole('option').filter({ hasText: '周明澈' }).first()
    await expect(person).toBeVisible()
    await person.click()
    await page.keyboard.press('Escape')
    await page.getByRole('button', { name: '查关联人物', exact: true }).click()
    await expect(page.locator('.query-context')).toContainText('周明澈')
    await expect(page.getByRole('alert')).toHaveCount(0)
  } finally {
    release()
  }
})
