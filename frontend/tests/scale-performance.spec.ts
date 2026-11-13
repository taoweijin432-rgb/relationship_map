import { startPersonQuery, submit, graphView } from './helpers'
import { test, expect, type Page, type Response } from '@playwright/test'
import { writeFile } from 'node:fs/promises'

declare global {
  interface Window {
    relationshipLongTasks?: { startTime: number; duration: number }[]
  }
}

async function settled(page: Page) {
  await expect(page.getByTestId('graph-canvas')).toHaveAttribute('aria-busy', 'false')
  await expect(page.locator('.graph-fallback')).toHaveCount(0)
  await page.evaluate(
    () =>
      new Promise<void>((resolve) =>
        requestAnimationFrame(() => requestAnimationFrame(() => resolve())),
      ),
  )
}

test('R01 可选规模浏览器观察：导航、实体筛选与关系图', async ({ page, browser }) => {
  test.skip(process.env.RELATIONSHIP_SCALE_BROWSER !== '1', '仅显式规模观察时运行')
  test.setTimeout(180000)
  const output = process.env.RELATIONSHIP_SCALE_OUTPUT
  if (!output) throw new Error('缺少规模浏览器输出文件')
  await page.addInitScript(() => {
    window.relationshipLongTasks = []
    new PerformanceObserver((list) => {
      list.getEntries().forEach((entry) =>
        window.relationshipLongTasks?.push({
          startTime: entry.startTime,
          duration: entry.duration,
        }),
      )
    }).observe({ type: 'longtask', buffered: true })
  })
  const errors: string[] = []
  page.on('pageerror', (error) => errors.push(error.message))
  const samples: object[] = []
  const network: Promise<object>[] = []
  let round = 0
  let scenario = ''
  page.on('response', (response) => {
    if (response.url().includes('/api/v1/')) network.push(networkSample(response, round, scenario))
  })
  for (round = 0; round < 3; round++) {
    for (const company of [null, '虚构热门集团', '虚构公司0999']) {
      scenario = company ?? 'person_ordinary'
      const start = Date.now()
      const metaPromise = page.waitForResponse((response) =>
        response.url().endsWith('/api/v1/meta'),
      )
      await page.goto('/')
      await startPersonQuery(page)
      const metadata = (await (await metaPromise).json()) as {
        data_version: string
        person_count: number
      }
      expect(metadata.data_version).toMatch(/^scale-v1-/)
      await expect(page.getByTestId('person-p:000002')).toBeVisible()
      await graphView(page)
      await settled(page)
      const navigationMs = Date.now() - start
      let lookupMs = 0
      let queryToGraphMs = 0
      if (company) {
        await page.getByRole('button', { name: '按条件找人', exact: true }).click()
        await submit(page)
        await expect(page.getByTestId('person-p:000001')).toBeVisible()
        await graphView(page)
        await settled(page)
        await page.getByRole('button', { name: '人物与经历', exact: true }).click()
        const lookupStart = Date.now()
        await page.getByTestId('company-select').click()
        await page.getByTestId('company-select').getByRole('combobox').fill(company)
        const option = page.getByRole('option', { name: company, exact: true })
        await expect(option).toBeVisible()
        lookupMs = Date.now() - lookupStart
        const queryStart = Date.now()
        const resultPromise = page.waitForResponse(
          (response) =>
            response.url().endsWith('/api/v1/persons/search') &&
            (
              response.request().postDataJSON() as { organization_ids: string[] }
            ).organization_ids.includes(company === '虚构热门集团' ? 'org:hot' : 'org:0999'),
        )
        await option.click()
        await page.keyboard.press('Escape')
        await submit(page)
        const result = (await (await resultPromise).json()) as {
          items: { person: { id: string } }[]
        }
        if (result.items[0])
          await expect(page.getByTestId(`person-${result.items[0].person.id}`)).toBeVisible()
        else await expect(page.getByText('暂无匹配人物', { exact: true })).toBeVisible()
        await graphView(page)
        await settled(page)
        queryToGraphMs = Date.now() - queryStart
      }
      const tasks = await page.evaluate(() => window.relationshipLongTasks ?? [])
      samples.push({
        round,
        scenario,
        data_version: metadata.data_version,
        active_people: metadata.person_count,
        navigation_ready_ms: navigationMs,
        entity_lookup_ms: lookupMs,
        selection_to_graph_ms: queryToGraphMs,
        long_tasks: tasks,
        largest_long_task_ms: Math.max(0, ...tasks.map((task) => task.duration)),
      })
    }
  }
  await Promise.all(network)
  await writeFile(
    output,
    JSON.stringify(
      {
        report_version: '1',
        browser: browser.version(),
        warning:
          '本机 Chrome、Vite 开发服务、串行交互；非生产静态包性能或并发容量，未清空操作系统缓存',
        samples,
        network: await Promise.all(network),
        page_errors: errors,
      },
      null,
      2,
    ),
  )
  expect(errors).toEqual([])
})

async function networkSample(response: Response, round: number, scenario: string): Promise<object> {
  try {
    const bytes = await response.body()
    return {
      round,
      scenario,
      url: new URL(response.url()).pathname,
      status: response.status(),
      bytes: bytes.length,
      timing: response.request().timing(),
      server_timing: response.headers()['server-timing'],
    }
  } catch (error) {
    return { round, scenario, url: response.url(), error: String(error) }
  }
}
