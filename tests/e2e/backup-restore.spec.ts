import { test, expect } from '../support/electron-fixture';
import { mkdtemp, readFile, writeFile, access } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { createHash } from 'node:crypto';
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
const execute=promisify(execFile);

async function publishChat(desktop:any,text:string) {
  await desktop.page.getByRole('textbox',{name:'消息输入'}).fill(text);
  await desktop.page.getByRole('button',{name:'发送',exact:true}).click();
  await expect(desktop.page.locator('.message.assistant')).toHaveCount(1,{timeout:30000});
  await expect(desktop.page.locator('.run-notice')).toHaveCount(0,{timeout:10000});
  return await desktop.page.evaluate(()=>location.hash.split('/').at(-1));
}
async function storage(page:any) {
  await page.getByRole('button',{name:'设置',exact:true}).click();
  await page.getByRole('button',{name:'存储',exact:true}).click();
  await expect(page.getByRole('heading',{name:'备份与恢复'})).toBeVisible();
}
async function saveBackup(desktop:any,path:string) {
  // Substitute only a native dialog response and observe the real HTTP bytes.
  await desktop.app.evaluate(({dialog},path)=>{
    (dialog as any).showSaveDialog=async()=>({canceled:false,filePath:path});
    if(!(globalThis as any).__backupOriginalFetch){
      const original=globalThis.fetch;(globalThis as any).__backupOriginalFetch=original;
      globalThis.fetch=async(...args:Parameters<typeof fetch>)=>{
        const response=await original(...args);
        if(String(args[0]).includes('/v1/backups/')&&String(args[0]).endsWith('/download'))
          (globalThis as any).__backupDownload={sha256:response.headers.get('X-Content-SHA256'),contentType:response.headers.get('Content-Type'),status:response.status};
        return response;
      };
    }
  },path);
  await desktop.page.getByRole('button',{name:'创建并保存备份'}).click();
  await expect(desktop.page.getByRole('status').filter({hasText:'已保存备份'})).toBeVisible({timeout:30000});
}

test('storage create entry saves a verified ZIP of the actual published chat',async({desktop},testInfo)=>{
  test.setTimeout(60000);const cid=await publishChat(desktop,'本轮发布后保存一致性备份。');
  const output=await mkdtemp(join(tmpdir(),'desktop-backup-'));const path=join(output,'backup.zip');
  await storage(desktop.page);await saveBackup(desktop,path);
  const bytes=await readFile(path);expect(bytes.subarray(0,2).toString()).toBe('PK');
  const header=await desktop.app.evaluate(()=>(globalThis as any).__backupDownload);
  expect(header.status).toBe(200);expect(header.contentType).toContain('application/zip');
  expect(createHash('sha256').update(bytes).digest('hex')).toBe(header.sha256);
  const script="import zipfile,json,hashlib,sys; z=zipfile.ZipFile(sys.argv[1]); m=json.loads(z.read('manifest.json')); checks=[hashlib.sha256(z.read(f['path'])).hexdigest()==f['sha256'] and len(z.read(f['path']))==f['size_bytes'] for f in m['files']]; assert all(checks); assert m['credentials_included'] is False; print(json.dumps(dict(schema=m['schema_version'],files=len(checks),all_hashes_verified=all(checks),entries=z.namelist())))";
  const checked=await execute(resolve('services/orchestrator/.venv/Scripts/python.exe'),['-c',script,path],{windowsHide:true});
  const report=JSON.parse(checked.stdout);expect(report.schema).toBe(4);expect(report.files).toBeGreaterThan(1);
  await writeFile(testInfo.outputPath('backup-export.json'),JSON.stringify({cid,zip_sha256:header.sha256,...report},null,2));
  await desktop.page.screenshot({path:testInfo.outputPath('backup-created.png')});
});

test('storage restore entry reopens saved history through an actual managed backend restart',async({desktop},testInfo)=>{
  test.setTimeout(90000);const cid=await publishChat(desktop,'恢复后应保留的已发布问题。');
  const output=await mkdtemp(join(tmpdir(),'desktop-restore-'));const path=join(output,'backup.zip');
  await storage(desktop.page);await saveBackup(desktop,path);
  await desktop.page.evaluate(cid=>{location.hash='/chat/'+cid;},cid);
  await expect(desktop.page.locator('.message.assistant')).toHaveCount(1);
  await desktop.page.getByRole('textbox',{name:'消息输入'}).fill('备份后新增，恢复时不应误当旧快照内容。');
  await desktop.page.getByRole('button',{name:'发送',exact:true}).click();
  await expect(desktop.page.locator('.message.assistant')).toHaveCount(2,{timeout:30000});
  await expect(desktop.page.locator('.run-notice')).toHaveCount(0,{timeout:10000});
  const previousPid=await desktop.app.evaluate(()=>(globalThis as any).__desktopTest.getManagedPid());
  await desktop.app.evaluate(({dialog},path)=>{
    (dialog as any).showOpenDialog=async()=>({canceled:false,filePaths:[path]});
    (dialog as any).showMessageBox=async(_window:any,options:any)=>{(globalThis as any).__restoreConfirmation={message:options.message,detail:options.detail};return {response:1};};
  },path);
  await storage(desktop.page);await desktop.page.getByRole('button',{name:'选择备份并恢复'}).click();
  await expect(desktop.page.getByRole('status').filter({hasText:'已恢复'})).toBeVisible({timeout:30000});
  const currentPid=await desktop.app.evaluate(()=>(globalThis as any).__desktopTest.getManagedPid());
  expect(currentPid).not.toBe(previousPid);
  const configuration=JSON.parse(await readFile(join(desktop.userData,'managed-storage.json'),'utf8'));
  expect(configuration.dataRoot).toContain('workbench-restored-');
  await access(join(configuration.dataRoot,'workbench.sqlite3'));
  await access(join(desktop.userData,'workbench','workbench.sqlite3'));
  await desktop.page.evaluate(cid=>{location.hash='/chat/'+cid;},cid);
  await expect(desktop.page.locator('.message.user')).toHaveCount(1);
  await expect(desktop.page.locator('.message.assistant')).toHaveCount(1);
  await expect(desktop.page.locator('.message.user').getByText('恢复后应保留的已发布问题。',{exact:true})).toBeVisible();
  await expect(desktop.page.locator('.message.user').getByText('备份后新增，恢复时不应误当旧快照内容。',{exact:true})).toHaveCount(0);
  const confirmation=await desktop.app.evaluate(()=>(globalThis as any).__restoreConfirmation);
  expect(confirmation.message).toContain('已核验');expect(confirmation.detail).toContain('凭证');
  const sourceCount=await execute(resolve('services/orchestrator/.venv/Scripts/python.exe'),['-c',"import sqlite3,sys; c=sqlite3.connect(sys.argv[1]); print(c.execute('SELECT COUNT(*) FROM turns').fetchone()[0]); c.close()",join(desktop.userData,'workbench','workbench.sqlite3')],{windowsHide:true});
  expect(Number(sourceCount.stdout.trim())).toBe(2);
  await writeFile(testInfo.outputPath('restore-managed-restart.json'),JSON.stringify({previous_pid:previousPid,current_pid:currentPid,source_retained:true,original_turns:2,restored_turns:1,confirmation},null,2));
  await desktop.page.screenshot({path:testInfo.outputPath('history-restored.png')});
});
