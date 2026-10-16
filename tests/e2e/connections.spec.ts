import { test, expect } from '../support/electron-fixture';
test('connection page keeps demonstrations distinct from verified real identities',async({desktop})=>{
  const {page}=desktop;await page.getByRole('button',{name:'设置',exact:true}).click();await expect(page.getByRole('heading',{name:'模型连接'})).toBeVisible();await expect(page.getByText('演示 · 模拟连接',{exact:true}).first()).toBeVisible();expect(await page.locator('.connection-state.verified').count()).toBe(0);await page.getByRole('button',{name:'检测连接'}).first().click();await expect(page.getByText('已检查运行注册状态；尚未实际调用模型。')).toBeVisible();
});
