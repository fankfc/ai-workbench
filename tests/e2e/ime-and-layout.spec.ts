import { test, expect } from '../support/electron-fixture';

test('composition and internal replay retain focus without transient leak', async ({ desktop }, testInfo) => {
  const { page } = desktop;
  await page.evaluate(() => {
    (window as any).internalLeaks = [];
    new MutationObserver(() => {
      if (document.body.textContent?.includes('INTERNAL_ENGLISH_CANARY')) (window as any).internalLeaks.push('INTERNAL_ENGLISH_CANARY');
    }).observe(document.body, { subtree: true, childList: true, characterData: true });
  });
  const composer = page.getByRole('textbox', { name: '消息输入' });
  await composer.fill('输入法验收');
  await composer.dispatchEvent('compositionstart');
  await composer.press('Enter');
  const compositionSubmits = await page.locator('.message.user').count();
  expect(compositionSubmits).toBe(0);
  await composer.dispatchEvent('compositionend');
  const focusLost = await composer.evaluate(element => document.activeElement !== element);
  expect(focusLost).toBe(false);
  await page.getByRole('button', { name: '发送', exact: true }).click();
  await expect(page.locator('.message.assistant')).toHaveCount(1, { timeout: 15000 });
  for (const kind of ['translation.delta', 'model.delta', 'tool.delta']) await desktop.emitInternal(kind, 'INTERNAL_ENGLISH_CANARY');
  const englishLeaks = await page.evaluate(() => (window as any).internalLeaks as string[]);
  expect(englishLeaks).toEqual([]);
  expect(JSON.stringify(await desktop.getPublicFrames())).not.toContain('INTERNAL_ENGLISH_CANARY');
  await testInfo.attach('gui-observations', { body: JSON.stringify({ build_id: process.env.WORKBENCH_QA_BUILD_ID,
    actual_electron: true, composition_submits: compositionSubmits, focus_lost: focusLost, english_leaks: englishLeaks,
    ime_method: 'synthetic composition events; real Windows IME pending', provider_boundary: 'fake' }), contentType: 'application/json' });
  await page.screenshot({ path: testInfo.outputPath('composition-and-replay.png') });
});
