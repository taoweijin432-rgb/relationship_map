// 只测实际保存响应的Chrome JSON.parse，不访问外站、不改查询API或页面资源。
import { readFile, writeFile } from "node:fs/promises";
import { resolve, join } from "node:path";
import { createRequire } from "node:module";

const require = createRequire(
  new URL("../frontend/package.json", import.meta.url),
);
const { chromium } = require("@playwright/test");
const directory = resolve(process.argv[2]);
const source = JSON.parse(
  await readFile(join(directory, "report.json"), "utf8"),
);
if (!source.passed) throw new Error("只测量已经通过实际HTTP校验的响应");
const browser = await chromium.launch({ channel: "chrome", headless: true });
const samples = [];
try {
  for (const row of source.samples) {
    const body = await readFile(join(directory, `${row.name}.json`), "utf8");
    const context = await browser.newContext();
    try {
      const page = await context.newPage();
      const sample = await page.evaluate((body) => {
        const durations = [];
        let keys = 0;
        for (let index = 0; index < 32; index++) {
          const start = performance.now();
          const value = JSON.parse(body);
          durations.push(performance.now() - start);
          keys += Object.keys(value).length;
        }
        const first = durations.shift();
        durations.sort((a, b) => a - b);
        return {
          first_ms: first,
          warm_samples: durations.length,
          warm_p50_ms: durations[Math.ceil(durations.length * 0.5) - 1],
          warm_p95_ms: durations[Math.ceil(durations.length * 0.95) - 1],
          parsed_key_count: keys,
        };
      }, body);
      samples.push({ name: row.name, body_bytes: row.body_bytes, ...sample });
    } finally {
      await context.close();
    }
  }
  await writeFile(
    join(directory, "browser-parse.json"),
    JSON.stringify(
      {
        browser: browser.version(),
        environment: "desktop-headless-chrome",
        samples,
      },
      null,
      2,
    ),
    { flag: "wx", mode: 0o600 },
  );
  console.log(JSON.stringify({ passed: true, samples: samples.length }));
} finally {
  await browser.close();
}
