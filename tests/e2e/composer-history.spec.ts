import { test, expect } from '../support/electron-fixture';
import { mkdtemp, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
test('IME enter does not submit, approved history survives reload and drafts remain per conversation',async({desktop})=>{
  const {page}=desktop;const composer=page.getByRole('textbox',{name:'消息输入'});await composer.fill('中文任务');await composer.dispatchEvent('compositionstart');await composer.press('Enter');expect(await page.evaluate(()=>location.hash)).toBe('');await composer.dispatchEvent('compositionend');await page.getByRole('button',{name:'发送',exact:true}).click();
  await expect(page.locator('.message.user')).toHaveCount(1);await expect(page.locator('.message.assistant')).toHaveCount(1,{timeout:15000});await expect(composer).toHaveValue('');
  await composer.fill('后续草稿');await page.reload();await expect(composer).toHaveValue('后续草稿');await expect(page.locator('.message.user')).toHaveCount(1);await expect(page.locator('.message.assistant')).toHaveCount(1);
  await page.getByRole('button',{name:'新建会话'}).click();await composer.fill('新会话草稿');await page.locator('.conversation-title').first().click();await expect(composer).toHaveValue('后续草稿');
});
test('only a native selected attachment is imported and the complete material reaches the task',async({desktop})=>{
  const root=await mkdtemp(join(tmpdir(),'desktop-attachment-'));const input=join(root,'材料.md');await writeFile(input,'# 用户材料\n\n保留材料全文。','utf8');await desktop.app.evaluate(({dialog},input)=>{(dialog as any).showOpenDialog=async()=>({canceled:false,filePaths:[input]});},input);await desktop.page.getByRole('button',{name:'添加文件'}).click();await expect(desktop.page.locator('.attachment-name')).toHaveText('材料.md');expect(await desktop.page.evaluate(()=>document.body.textContent)).not.toContain(input);await desktop.page.getByRole('textbox',{name:'消息输入'}).fill('请使用附件');await desktop.page.getByRole('button',{name:'发送',exact:true}).click();await expect(desktop.page.locator('.message.user')).toHaveCount(1);await expect(desktop.page.locator('.message.assistant')).toHaveCount(1,{timeout:15000});
});
test('double click sends one client request and script text cannot execute',async({desktop})=>{
  const {page}=desktop;await page.getByRole('textbox',{name:'消息输入'}).fill('<script>window.XSS_CANARY=true</script> 中文任务');await page.getByRole('button',{name:'发送',exact:true}).dblclick();await expect(page.locator('.message.user')).toHaveCount(1);await expect(page.locator('.message.assistant')).toHaveCount(1,{timeout:15000});expect(await page.evaluate(()=>(window as any).XSS_CANARY)).toBeUndefined();const frames=await desktop.getPublicFrames();expect(frames.filter((frame:any)=>frame.kind==='message.accepted')).toHaveLength(1);
});
