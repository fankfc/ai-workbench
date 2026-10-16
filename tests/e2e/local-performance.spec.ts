import { test, expect, launchDesktop } from '../support/electron-fixture';
import { mkdtemp } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

test('record two hundred input echo samples in the actual renderer', async ({ desktop }, testInfo) => {
  const { page } = desktop;
  const inputSamples: number[] = [];
  const acknowledgementSamples: number[] = [];
  const stateSamples: number[] = [];
  const acceptedTaskIds = new Set<string>();
  for (let i = 0; i < 200; i++) {
    const text = `中文输入性能 ${i}`;
    const started = await page.evaluate(() => performance.now());
    await page.getByRole('textbox', { name: '消息输入' }).fill(text);
    await page.evaluate(() => new Promise<void>(resolve => requestAnimationFrame(() => resolve())));
    inputSamples.push(await page.evaluate(start => performance.now() - start, started));
    await expect(page.getByRole('textbox', { name: '消息输入' })).toHaveValue(text);
  }
  for (let i = 0; i < 10; i++) {
    const text = `确认与持久状态采样 ${i}`;
    await page.getByRole('textbox', { name: '消息输入' }).fill(text);
    const started = await page.evaluate(() => performance.now());
    await page.getByRole('button', { name: '发送', exact: true }).click();
    await expect(page.locator('.message.user')).toHaveCount(i + 1);
    let acceptedTaskId = '';
    await expect.poll(async () => {
      const frames = await desktop.getPublicFrames();
      const accepted = frames.find((frame: any) => frame.kind === 'message.accepted'
        && frame.payload?.text === text && !acceptedTaskIds.has(frame.task_id)) as { task_id: string } | undefined;
      acceptedTaskId = accepted?.task_id ?? '';
      return acceptedTaskId;
    }).toBeTruthy();
    acceptedTaskIds.add(acceptedTaskId);
    acknowledgementSamples.push(await page.evaluate(start => performance.now() - start, started));
    const state = await page.evaluate(async taskId => window.workbench.getTask({ taskId }), acceptedTaskId);
    expect(state.task_id).toBe(acceptedTaskId);
    stateSamples.push(await page.evaluate(start => performance.now() - start, started));
    await expect(page.locator('.message.assistant')).toHaveCount(i + 1, { timeout: 15000 });
    await expect(page.locator('.run-notice')).toHaveCount(0);
  }
  await testInfo.attach('renderer-latency', { body: JSON.stringify({ build_id: process.env.WORKBENCH_QA_BUILD_ID,
    actual_electron: true, input_echo_samples_ms: inputSamples, ui_ack_samples_ms: acknowledgementSamples,
    state_visible_samples_ms: stateSamples, provider_boundary: 'fake',
    method: 'Playwright fill plus next animation frame; send acknowledgement waits for the current message.accepted event and new task ID; includes driver and polling overhead',
    missing: ['cancel feedback samples', '10000 task UI workload', '24h soak'] }), contentType: 'application/json' });
});

test('record bounded cold start and lifecycle samples', async ({}, testInfo) => {
  const requested = Number(process.env.WORKBENCH_QA_COLD_STARTS ?? 3);
  const cycles = Number(process.env.WORKBENCH_QA_LIFECYCLE_CYCLES ?? 3);
  if (!Number.isInteger(requested) || requested < 1 || requested > 30 || !Number.isInteger(cycles) || cycles < requested || cycles > 100) throw new Error('invalid bounded desktop run');
  test.setTimeout(cycles * 45000);
  const starts: number[] = [];
  const cleanup: { pid: number; cleaned: boolean }[] = [];
  for (let i = 0; i < cycles; i++) {
    const root = await mkdtemp(join(tmpdir(), 'workbench-performance-'));
    const start = performance.now();
    const { app, page } = await launchDesktop(root);
    try {
      if (i < requested) starts.push(performance.now() - start);
      await expect(page.getByRole('textbox', { name: '消息输入' })).toBeVisible();
      const pids = await app.evaluate(() => [(globalThis as any).__desktopTest.getManagedPid(), (globalThis as any).__desktopTest.getServicePid()]);
      await app.close();
      for (const pid of pids.filter(Boolean)) {
        await expect.poll(() => { try { process.kill(pid, 0); return false; } catch { return true; } }, { timeout: 5000 }).toBe(true);
        cleanup.push({ pid, cleaned: true });
      }
    } finally { await app.close().catch(() => {}); }
  }
  await testInfo.attach('desktop-lifecycle', { body: JSON.stringify({ build_id: process.env.WORKBENCH_QA_BUILD_ID,
    actual_electron: true, cold_start_samples_ms: starts, cycles, cleanup, provider_boundary: 'fake',
    method: 'fresh isolated user-data launch; filesystem and OS caches not cleared' }), contentType: 'application/json' });
});
