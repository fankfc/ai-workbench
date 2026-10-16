import { test, expect } from '../support/electron-fixture';
import { mkdtemp, access, readFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
test('usage has no invented savings, storage cleanup is previewed and diagnostics stay separate',async({desktop})=>{
  const {page}=desktop;await page.getByRole('button',{name:'用量',exact:true}).click();await expect(page.getByText('节省率未评测。尚无批准且可比较的独立基准。')).toBeVisible();await expect(page.getByText('不可计算',{exact:true})).toBeVisible();await page.getByRole('button',{name:'设置',exact:true}).click();await page.getByRole('button',{name:'存储',exact:true}).click();await page.getByRole('button',{name:'预览可清理内容'}).click();await expect(page.getByRole('heading',{name:'可清理对象：0'})).toBeVisible();await page.getByRole('button',{name:'诊断',exact:true}).click();await expect(page.getByRole('button',{name:'保存脱敏诊断'})).toBeVisible();await page.getByRole('button',{name:'新建会话'}).click();await expect(page.getByText('节省率未评测。尚无批准且可比较的独立基准。')).toHaveCount(0);
});
test('selected directory migration keeps the source and restarts the owned backend',async({desktop})=>{
  const target=await mkdtemp(join(tmpdir(),'desktop-relocation-'));await desktop.app.evaluate(({dialog},target)=>{(dialog as any).showOpenDialog=async()=>({canceled:false,filePaths:[target]});},target);
  const firstPid=await desktop.app.evaluate(()=>(globalThis as any).__desktopTest.getManagedPid());
  await desktop.page.getByRole('button',{name:'设置',exact:true}).click();await desktop.page.getByRole('button',{name:'存储',exact:true}).click();await desktop.page.getByRole('button',{name:'选择目录并预检'}).click();await desktop.page.getByRole('button',{name:'确认迁移并重新连接'}).click();await expect(desktop.page.getByText('目录副本已核验，本地服务已重新连接。原目录已保留。')).toBeVisible({timeout:15000});
  const newPid=await desktop.app.evaluate(()=>(globalThis as any).__desktopTest.getManagedPid());expect(newPid).not.toBe(firstPid);await access(join(target,'workbench.sqlite3'));await access(join(desktop.userData,'workbench/workbench.sqlite3'));const managed=JSON.parse(await readFile(join(desktop.userData,'managed-storage.json'),'utf8'));expect(managed.dataRoot).toBe(target);expect(await desktop.page.evaluate(()=>JSON.stringify(window.workbench))).not.toContain(target);
});
