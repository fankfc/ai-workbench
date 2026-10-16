import { test, expect, launchDesktop } from '../support/electron-fixture';
import { mkdtemp } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { spawn } from 'node:child_process';
import { _electron } from '@playwright/test';
test('actual isolated Electron exposes only a business bridge',async({desktop})=>{
  const boundary=await desktop.page.evaluate(()=>({require:typeof (window as any).require,process:typeof (window as any).process,keys:Object.keys(window.workbench),invoke:typeof (window.workbench as any).invoke}));
  expect(boundary.require).toBe('undefined');expect(boundary.process).toBe('undefined');expect(boundary.invoke).toBe('undefined');expect(boundary.keys).not.toContain('token');expect(boundary.keys).not.toContain('readFile');
  await expect(desktop.page.getByText('演示模式',{exact:true})).toBeVisible();
});
test('disconnect keeps the draft and blocks sending',async({desktop})=>{
  await desktop.app.evaluate(async()=>{const bridge=(globalThis as any).__desktopTest;await bridge.stopBackend();});
  await expect(desktop.page.getByText(/当前进度已保存/)).toBeVisible();await desktop.page.getByRole('textbox',{name:'消息输入'}).fill('离线草稿');await expect(desktop.page.getByRole('button',{name:'发送',exact:true})).toBeDisabled();
});
test('default real mode keeps all unverified connections disabled',async()=>{
  const root=await mkdtemp(join(tmpdir(),'desktop-real-no-generation-'));const {app,page}=await launchDesktop(root,'real');
  try{await page.getByLabel('任务类型').selectOption('document');await page.getByLabel('文档受众').fill('研究组');await page.getByLabel('文档用途').fill('完整报告');await page.getByLabel('PDF',{exact:true}).check();await page.getByRole('textbox',{name:'消息输入'}).fill('真实模式草稿');await expect(page.getByRole('button',{name:'发送',exact:true})).toBeDisabled();await expect(page.getByText('先完成模型连接，即可开始。草稿会保留。')).toBeVisible();await expect(page.getByText('演示模式',{exact:true})).toHaveCount(0);}finally{await app.close();}
});
test('second launch focuses the existing instance without starting another backend',async({desktop})=>{
  const firstPid=await desktop.app.evaluate(()=>(globalThis as any).__desktopTest.getManagedPid());
  const second=spawn(resolve('node_modules/electron/dist/electron.exe'),[resolve('apps/desktop/dist-test/main/index.cjs'),`--user-data-dir=${desktop.userData}`,'--demo'],{env:{...process.env,ELECTRON_RUN_AS_NODE:undefined},windowsHide:true,stdio:'ignore'});
  await new Promise<void>((resolve,reject)=>{const timer=setTimeout(()=>{second.kill();reject(new Error('second instance did not exit'));},5000);second.once('exit',()=>{clearTimeout(timer);resolve();});});
  expect(await desktop.app.evaluate(()=>(globalThis as any).__desktopTest.getManagedPid())).toBe(firstPid);
});
test('production bundle contains no test injection entry',async()=>{
  const root=await mkdtemp(join(tmpdir(),'desktop-production-'));const app=await _electron.launch({executablePath:resolve('node_modules/electron/dist/electron.exe'),args:[resolve('apps/desktop/dist/main/index.cjs'),`--user-data-dir=${root}`,'--demo'],env:{...process.env,ELECTRON_RUN_AS_NODE:undefined}});
  try{const page=await app.firstWindow();await expect(page.getByText('演示模式',{exact:true})).toBeVisible();expect(await app.evaluate(()=>typeof (globalThis as any).__desktopTest)).toBe('undefined');expect(await page.evaluate(()=>typeof (window as any).__desktopTest)).toBe('undefined');expect(await page.evaluate(()=>typeof (window as any).require)).toBe('undefined');}finally{await app.close();}
});
