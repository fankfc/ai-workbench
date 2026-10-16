import { _electron, expect } from '@playwright/test';
import { mkdtemp, mkdir, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
const result = {};
const data = await mkdtemp(join(tmpdir(), 'desktop-independent-review-'));
const app = await _electron.launch({
  executablePath: resolve('node_modules/electron/dist/electron.exe'),
  args: [resolve('apps/desktop/dist-test/main/index.cjs'), `--user-data-dir=${data}`, '--demo'],
  env: { ...process.env, ELECTRON_RUN_AS_NODE: undefined },
});
try {
  const page = await app.firstWindow();
  await expect.poll(() => app.evaluate(() => globalThis.__desktopTest.getBackendStatus().state), { timeout: 30000 }).toBe('ready');
  const composer = page.getByRole('textbox', { name: '消息输入' });
  await composer.fill('复核：请给出一个公开回答');
  await page.getByRole('button', { name: '发送', exact: true }).click();
  await expect(page.locator('.message.assistant')).toHaveCount(1, { timeout: 15000 });
  const beforeOffline = await page.locator('.message').count();
  await app.evaluate(async () => globalThis.__desktopTest.stopBackend());
  await expect(page.getByRole('button', { name: '重试连接', exact: true })).toBeVisible();
  await expect(page.locator('.message')).toHaveCount(beforeOffline);
  result.disconnect = { beforeOffline, afterOffline: await page.locator('.message').count(), hash: await page.evaluate(() => location.hash) };
  await page.getByRole('button', { name: '重试连接', exact: true }).click();
  await expect.poll(() => app.evaluate(() => globalThis.__desktopTest.getBackendStatus().state), { timeout: 30000 }).toBe('ready');
  await expect(page.locator('.message.assistant')).toHaveCount(1);
  await app.evaluate(({ ipcMain }) => {
    const handlers = ipcMain._invokeHandlers;
    globalThis.__reviewOriginalSubmit = handlers.get('workbench:submitTurn');
    handlers.set('workbench:submitTurn', async (...args) => {
      const accepted = await globalThis.__reviewOriginalSubmit(...args);
      await new Promise(resolve => setTimeout(resolve, 2500));
      return accepted;
    });
  });
  await composer.fill('复核：请再次给出回答');
  await page.getByRole('button', { name: '发送', exact: true }).click();
  await expect(page.locator('.message.assistant')).toHaveCount(2, { timeout: 15000 });
  await page.waitForTimeout(3500);
  result.lateSubmitReceipt = { publishedAnswers: await page.locator('.message.assistant').count(), waitingNotices: await page.locator('.run-notice').count(), waitingText: await page.locator('.run-notice').allTextContents() };
  await composer.fill('第三轮草稿');
  result.lateSubmitReceipt.sendDisabled = await page.getByRole('button', { name: '发送', exact: true }).isDisabled();
  expect(result.lateSubmitReceipt.waitingNotices).toBe(0);
  expect(result.lateSubmitReceipt.sendDisabled).toBe(false);
  await page.reload();
  await expect(page.locator('.message.assistant')).toHaveCount(2);
  result.lateSubmitReceipt.afterReloadWaiting = await page.locator('.run-notice').count();
  await page.getByRole('button', { name: '新建会话', exact: true }).click();
  await composer.fill('复核：切换页面中的发送');
  await page.getByRole('button', { name: '发送', exact: true }).click();
  await expect(page.locator('.message.user')).toHaveCount(1);
  const submittedConversation = await page.evaluate(() => location.hash);
  await page.getByRole('button', { name: '新建会话', exact: true }).click();
  await composer.fill('新会话不应被旧任务占用');
  await page.waitForTimeout(3500);
  result.sessionSwitch = { submittedConversation, currentConversation: await page.evaluate(() => location.hash), waitingNotices: await page.locator('.run-notice').count(), sendDisabled: await page.getByRole('button', { name: '发送', exact: true }).isDisabled(), displayedMessages: await page.locator('.message').count() };
  expect(result.sessionSwitch.waitingNotices).toBe(0);
  expect(result.sessionSwitch.sendDisabled).toBe(false);
  await app.evaluate(({ ipcMain }) => {
    const handlers = ipcMain._invokeHandlers;
    const originalUsage = handlers.get('workbench:getUsage');
    globalThis.__reviewUsageQueries = [];
    handlers.set('workbench:getUsage', async (event, input) => {
      globalThis.__reviewUsageQueries.push(structuredClone(input));
      return originalUsage(event, input);
    });
  });
  await page.getByRole('button', { name: '用量', exact: true }).click();
  await page.getByLabel('开始日期').fill('2026-10-14');
  await page.getByLabel('结束日期').fill('2026-10-14');
  await expect.poll(() => app.evaluate(() => globalThis.__reviewUsageQueries.at(-1)?.date_to)).toBe('2026-10-14T15:59:59.999Z');
  const capturedQuery = await app.evaluate(() => globalThis.__reviewUsageQueries.at(-1));
  result.dateRange = await page.evaluate(query => {
    const chosen = '2026-10-14';
    const from = query.date_from;
    const to = query.date_to;
    return { timezone: Intl.DateTimeFormat().resolvedOptions().timeZone, chosen, emittedFrom: from, emittedTo: to, localFrom: new Date(from).toString(), localTo: new Date(to).toString() };
  }, capturedQuery);
  expect(result.dateRange.emittedFrom).toBe('2026-10-13T16:00:00.000Z');
  await writeFile(resolve('artifacts/acceptance/independent-desktop-review/revalidation.json'), JSON.stringify({ ...result, userData: data, fourOriginalFindingsFixed: true, modelCalls: 0 }, null, 2));
  console.log(JSON.stringify(result, null, 2));
} finally {
  await app.close();
}
