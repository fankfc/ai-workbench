import { test, expect } from '../support/electron-fixture';

test('untrusted renderer has no command or file authority; user script stays text', async ({ desktop }, testInfo) => {
  const boundary = await desktop.page.evaluate(() => ({ require: typeof (window as any).require,
    process: typeof (window as any).process, invoke: typeof (window.workbench as any).invoke,
    readFile: typeof (window.workbench as any).readFile }));
  expect(Object.values(boundary)).toEqual(['undefined', 'undefined', 'undefined', 'undefined']);
  await desktop.page.getByRole('textbox', { name: '消息输入' }).fill('<script>window.SECURITY_EXECUTED_47 = true</script>');
  await desktop.page.getByRole('button', { name: '发送', exact: true }).click();
  await expect(desktop.page.locator('.message.assistant')).toHaveCount(1, { timeout: 15000 });
  expect(await desktop.page.evaluate(() => (window as any).SECURITY_EXECUTED_47)).toBeUndefined();
  await testInfo.attach('security-boundary', { body: JSON.stringify({ actual_electron: true,
    provider_boundary: 'fake', boundary, executed_payloads: 0 }), contentType: 'application/json' });
});
