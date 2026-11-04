// Own application only: headless browser, real isolated frozen backend, no desktop access.
import { chromium } from 'playwright';
import fs from 'node:fs/promises';
import path from 'node:path';
import assert from 'node:assert/strict';
const output = path.resolve(process.env.SKY_UI_REPORT_DIR || '../artifacts/desktop-ui');
await fs.mkdir(output, { recursive: true });
const browser = await chromium.launch({
  executablePath: process.env.SKY_HEADLESS_BROWSER,
  headless: true,
  args: ['--disable-gpu'],
});
const page = await browser.newPage({
  baseURL: 'http://127.0.0.1:5178',
  viewport: { width: 1440, height: 960 },
  deviceScaleFactor: 1,
});
const errors = [],
  cases = [];
let version;
page.on('pageerror', (e) => errors.push(String(e)));
const check = async (name, fn) => {
  await fn();
  cases.push({ name, passed: true });
};
const visible = async (locator) => {
  await locator.waitFor({ state: 'visible', timeout: 15000 });
};
try {
  await page.goto('/', { waitUntil: 'networkidle' });
  await visible(page.getByText('本地引擎已连接', { exact: true }));
  const health = await page.request.get('/runtime-api/api/health');
  assert.ok(health.ok());
  ({ version } = await health.json());
  const packageVersion = JSON.parse(await fs.readFile('package.json', 'utf8')).version;
  assert.equal(version, packageVersion);
  await check('Homepage reads real persisted tasks', async () => {
    await visible(page.getByRole('button', { name: 'Ollama 仓库信息', exact: true }));
    assert.equal(await page.locator('body').evaluate((e) => e.scrollWidth > innerWidth), false);
    await page.screenshot({ path: path.join(output, 'home.png'), fullPage: true });
  });
  await check('Name search and clear', async () => {
    await page.getByRole('textbox', { name: '搜索任务' }).fill('__no_matching_task__');
    await visible(page.getByText('没有找到匹配任务', { exact: true }));
    await page.getByRole('button', { name: '清空搜索', exact: true }).click();
    await visible(page.getByRole('button', { name: 'Ollama 仓库信息', exact: true }));
  });
  await check('Create, copy, edit and delete a real draft', async () => {
    const name = '界面后台验收 ' + Date.now();
    await page.getByRole('button', { name: '新建任务', exact: true }).click();
    await page.getByRole('textbox', { name: '任务名称', exact: true }).fill(name);
    await page
      .getByRole('textbox', { name: '来源网址', exact: true })
      .fill('https://www.python.org/downloads/');
    await page.screenshot({ path: path.join(output, 'new-task.png'), fullPage: true });
    await page.getByRole('button', { name: '跳过预览', exact: true }).click();
    await page.getByRole('button', { name: '保存草稿', exact: true }).click();
    await visible(page.getByRole('button', { name, exact: true }));
    await page.getByRole('button', { name: '复制任务 ' + name, exact: true }).click();
    // Backend names are authoritative; locate the new copy by the shared source row.
    await page.waitForFunction((n) => document.querySelectorAll('.task-name').length >= 4, name);
    const labels = await page.locator('.task-name').allTextContents();
    const copyName = labels.find((v) => v.startsWith(name) && v !== name);
    assert.ok(copyName, 'copied draft must exist');
    await page.getByRole('button', { name, exact: true }).click();
    await page.getByRole('textbox', { name: '任务名称', exact: true }).fill(name + ' 已编辑');
    await page.getByRole('button', { name: '跳过预览', exact: true }).click();
    await page.getByRole('button', { name: '保存草稿', exact: true }).click();
    for (const target of [name + ' 已编辑', copyName]) {
      await visible(page.getByRole('button', { name: '删除任务 ' + target, exact: true }));
      await page.getByRole('button', { name: '删除任务 ' + target, exact: true }).click();
      await page.getByRole('button', { name: '确认删除', exact: true }).click();
      await page.getByRole('button', { name: target, exact: true }).waitFor({ state: 'hidden' });
    }
  });
  await check('Real run logs', async () => {
    await page.getByRole('button', { name: '运行日志 Ollama 仓库信息', exact: true }).click();
    await visible(page.locator('.log-line').first());
    await page.getByRole('button', { name: '关闭', exact: true }).last().click();
  });
  await check('Results, evidence and review persist', async () => {
    await page.getByRole('button', { name: '查看结果 Ollama 仓库信息', exact: true }).click();
    await visible(page.locator('.result-table tbody tr').first());
    await page.screenshot({ path: path.join(output, 'results.png'), fullPage: true });
    await page.locator('.result-table tbody tr').first().click();
    await visible(page.locator('.evidence-sheet .selectable'));
    assert.equal(
      await page.locator('.evidence-sheet .selectable').textContent(),
      'https://api.github.com/repos/ollama/ollama',
    );
    await page.getByRole('button', { name: '标记已审核', exact: true }).click();
    await visible(page.locator('.review.approved').first());
    await page.screenshot({ path: path.join(output, 'evidence.png'), fullPage: true });
    await page.getByRole('button', { name: '关闭证据', exact: true }).click();
    const downloadPromise = page.waitForEvent('download');
    await page.getByRole('button', { name: '导出 Excel', exact: true }).click();
    const download = await downloadPromise;
    await download.saveAs(path.join(output, 'ui-export.xlsx'));
    assert.ok((await fs.stat(path.join(output, 'ui-export.xlsx'))).size > 1000);
  });
  await check('Local knowledge without inference', async () => {
    await page.getByRole('button', { name: 'AI 助手', exact: true }).click();
    await page.getByRole('button', { name: '本地知识检索', exact: true }).click();
    await page.getByRole('textbox', { name: '输入问题', exact: true }).fill('PDF OCR');
    await page.getByRole('button', { name: '发送问题', exact: true }).click();
    await visible(page.locator('.knowledge-results article').first());
    await page.screenshot({ path: path.join(output, 'knowledge.png'), fullPage: true });
  });
  await check('Settings expose actual Ollama model and support limits', async () => {
    const response = await page.request.get('/runtime-api/api/ai/status');
    assert.ok(response.ok());
    const { ai, preferences } = await response.json();
    await page.getByRole('button', { name: '设置', exact: true }).click();
    await visible(page.getByText('qwen3.5:9b', { exact: true }));
    const modelState = !preferences.ai_enabled
      ? 'AI已关闭'
      : ai.installed
        ? '已安装'
        : ai.connected
          ? '模型缺失'
          : '服务未连接';
    await visible(page.getByText(modelState, { exact: true }));
    await page.screenshot({ path: path.join(output, 'settings.png'), fullPage: true });
  });
  await check('Minimum supported viewport has no page overflow', async () => {
    await page.setViewportSize({ width: 1060, height: 680 });
    await page
      .getByRole('button', { name: /任务清单/ })
      .first()
      .click();
    assert.equal(await page.locator('body').evaluate((e) => e.scrollWidth > innerWidth), false);
    await page.screenshot({ path: path.join(output, 'minimum-size.png'), fullPage: true });
  });
  assert.deepEqual(errors, []);
} finally {
  await fs.writeFile(
    path.join(output, 'report.json'),
    JSON.stringify(
      {
        desktop_used: false,
        version,
        headless: true,
        cases,
        errors,
        passed: cases.length === 8 && errors.length === 0,
      },
      null,
      2,
    ),
  );
  await browser.close();
}
