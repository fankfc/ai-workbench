import { test, expect } from '../support/electron-fixture';
import { writeFile } from 'node:fs/promises';
for(const [width,height] of [[1440,900],[1280,800],[1024,768],[320,768]])test(`layout fits ${width}x${height}`,async({desktop},testInfo)=>{
  await desktop.app.evaluate(({BrowserWindow},size)=>BrowserWindow.getAllWindows()[0].setContentSize(size.width,size.height),{width,height});
  await desktop.page.getByRole('textbox',{name:'消息输入'}).fill('长中文草稿'.repeat(40));
  const metrics=await desktop.page.evaluate(()=>({width:innerWidth,scroll:document.documentElement.scrollWidth,send:document.querySelector('button.primary')?.getBoundingClientRect().toJSON()}));
  expect(metrics.scroll).toBeLessThanOrEqual(metrics.width);await expect(desktop.page.getByRole('button',{name:'发送',exact:true})).toBeVisible();
  await desktop.page.screenshot({path:testInfo.outputPath(`layout-${width}.png`)});
});
test('theme, large text and 200 percent zoom retain the composer',async({desktop},testInfo)=>{
  await desktop.page.getByRole('button',{name:'设置',exact:true}).click();await desktop.page.getByRole('button',{name:'偏好',exact:true}).click();await desktop.page.getByLabel('主题',{exact:true}).selectOption('dark');await desktop.page.getByLabel('正文字号').selectOption('22');await desktop.page.getByRole('button',{name:'保存偏好'}).click();await expect(desktop.page.getByText('偏好已保存。')).toBeVisible();
  await desktop.app.evaluate(({BrowserWindow})=>BrowserWindow.getAllWindows()[0].webContents.setZoomFactor(2));await desktop.page.keyboard.press('Control+n');
  await expect(desktop.page.getByRole('textbox',{name:'消息输入'})).toBeVisible();expect(await desktop.page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);const bounds=await desktop.page.getByRole('button',{name:'发送',exact:true}).evaluate(element=>({rect:element.getBoundingClientRect().toJSON(),width:innerWidth,height:innerHeight}));expect(bounds.rect.bottom).toBeLessThanOrEqual(bounds.height);expect(bounds.rect.right).toBeLessThanOrEqual(bounds.width);await writeFile(testInfo.outputPath('zoom-bounds.json'),JSON.stringify(bounds));const png=await desktop.app.evaluate(async({BrowserWindow})=>(await BrowserWindow.getAllWindows()[0].webContents.capturePage()).toPNG().toString('base64'));await writeFile(testInfo.outputPath('dark-22-200percent.png'),Buffer.from(png,'base64'));
});
