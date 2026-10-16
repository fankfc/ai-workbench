import { test as base, expect, _electron, type ElectronApplication, type Page } from '@playwright/test';
import { mkdtemp, writeFile, mkdir } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { resolve, join } from 'node:path';
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
export type DesktopFixture={app:ElectronApplication;page:Page;userData:string;getPublicFrames:()=>Promise<unknown[]>;seedBundle:()=>Promise<any>;emitInternal:(kind:string,text:string)=>Promise<void>};
const execute=promisify(execFile);
export async function launchDesktop(userData:string,mode:'fake'|'real'='fake'):Promise<{app:ElectronApplication;page:Page}> {
  const app=await _electron.launch({executablePath:resolve('node_modules/electron/dist/electron.exe'),args:[resolve('apps/desktop/dist-test/main/index.cjs'),`--user-data-dir=${userData}`,...(mode==='fake'?['--demo']:[])],env:{...process.env,ELECTRON_RUN_AS_NODE:undefined},timeout:20000});
  try{const page=await app.firstWindow();await page.waitForFunction(()=>!!window.workbench);await expect.poll(()=>app.evaluate(()=> (globalThis as any).__desktopTest.getBackendStatus()?.state),{timeout:30000}).toBe('ready');await expect(page.getByText('正在连接本地服务…',{exact:true})).toHaveCount(0);return {app,page};}catch(error){const status=await app.evaluate(()=>(globalThis as any).__desktopTest?.getBackendStatus()).catch(()=>null);await app.close().catch(()=>{});throw new Error(`${error instanceof Error?error.message:'Desktop startup failed'}; backend_status=${JSON.stringify(status)}`);}
}
export const test=base.extend<{desktop:DesktopFixture}>({desktop:async({},use,testInfo)=>{
  const userData=await mkdtemp(join(tmpdir(),'workbench-electron-'));let launched:Awaited<ReturnType<typeof launchDesktop>>|undefined;const logs:string[]=[];
  try {
    launched=await launchDesktop(userData);const {app,page}=launched;app.process().stderr?.on('data',chunk=>logs.push(String(chunk)));page.on('pageerror',error=>logs.push(error.message));
    await use({app,page,userData,getPublicFrames:()=>app.evaluate(()=>(globalThis as any).__desktopTest.getPublicFrames()),seedBundle:async()=>{const result=await execute(resolve('services/orchestrator/.venv/Scripts/python.exe'),[resolve('tests/artifacts/seed_bundle.py'),'--data-root',join(userData,'workbench'),'--token','test-only-bundle-seed','--formats','markdown,pdf,docx'],{cwd:resolve('services/orchestrator'),windowsHide:true,timeout:60000,maxBuffer:1024*1024});return JSON.parse(result.stdout);},emitInternal:async(kind,text)=>{
      const script="import sqlite3,json,sys,uuid; from app.api.turns import append_event; c=sqlite3.connect(sys.argv[1]); c.row_factory=sqlite3.Row; row=c.execute('SELECT * FROM task_runs ORDER BY created_at DESC LIMIT 1').fetchone(); append_event(c,row['turn_id'],row['task_id'],row['attempt_id'],sys.argv[2],{'text':sys.argv[3]},row['contract_version']); c.commit(); c.close()";
      await execute(resolve('services/orchestrator/.venv/Scripts/python.exe'),['-c',script,join(userData,'workbench/workbench.sqlite3'),kind,text],{cwd:resolve('services/orchestrator'),windowsHide:true});
      await page.waitForTimeout(750);await app.evaluate(()=>Promise.resolve());await page.evaluate(()=>new Promise<void>(resolve=>requestAnimationFrame(()=>requestAnimationFrame(()=>resolve()))));
    }});
    const pids=await app.evaluate(()=>[(globalThis as any).__desktopTest.getManagedPid(),(globalThis as any).__desktopTest.getServicePid()]);await app.close();launched=undefined;
    for(const pid of pids.filter(Boolean))await expect.poll(()=>{try{process.kill(pid,0);return true;}catch{return false;}},{timeout:5000}).toBe(false);
  } finally {
    if(launched){if(testInfo.status!==testInfo.expectedStatus)await launched.page.screenshot({path:testInfo.outputPath('failure.png')}).catch(()=>{});await launched.app.close().catch(()=>{});}
    await mkdir(testInfo.outputDir,{recursive:true});await writeFile(testInfo.outputPath('electron.log'),logs.join('\n'));await writeFile(testInfo.outputPath('fixture.json'),JSON.stringify({userData,time:new Date().toISOString(),actualElectron:true,mode:'fake'}));
  }
}});
export { expect };
