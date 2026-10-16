import { test, expect } from '../support/electron-fixture';

test('keyboard navigation and 200 percent zoom keep labelled composer visible', async ({ desktop }, testInfo) => {
  const { page } = desktop;
  const composer = page.getByRole('textbox', { name: '消息输入' });
  await composer.focus();
  await composer.press('Tab');
  const focused = await page.evaluate(() => ({ tag: document.activeElement?.tagName,
    label: document.activeElement?.getAttribute('aria-label'), text: document.activeElement?.textContent }));
  expect(focused.tag).toBe('BUTTON');
  await desktop.app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0].webContents.setZoomFactor(2));
  await expect(composer).toBeVisible();
  await expect(page.getByRole('button', { name: '发送', exact: true })).toBeVisible();
  await testInfo.attach('keyboard-observations', { body: JSON.stringify({ actual_electron: true,
    focused, narrator_verified: false, multiple_monitors_verified: false }), contentType: 'application/json' });
  await page.screenshot({ path: testInfo.outputPath('keyboard-zoom.png') });
});
