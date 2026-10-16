import { beforeEach, describe, expect, it, vi } from 'vitest';
import { mkdtemp, readFile, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { createHash } from 'node:crypto';
const { handlers, dialog } = vi.hoisted(()=>({handlers:new Map<string,any>(),dialog:{showSaveDialog:vi.fn(),showOpenDialog:vi.fn(),showMessageBox:vi.fn()}}));
vi.mock('electron',()=>({ipcMain:{handle:(name:string,handler:any)=>handlers.set(name,handler),removeHandler:(name:string)=>handlers.delete(name)},dialog}));
import { installBackupIpc } from '../../apps/desktop/src/main/backup-ipc';
import { validateCall } from '../../apps/desktop/src/shared/validation';

describe('backup IPC uses owner dialogs and opaque backend references',()=>{
  beforeEach(()=>{handlers.clear();vi.clearAllMocks();});
  const window:any={webContents:{mainFrame:{url:'workbench://desktop/index.html'}}};
  const event={sender:window.webContents,senderFrame:window.webContents.mainFrame};
  it('rejects renderer disk paths and wrong senders before opening a dialog',async()=>{
    const backend:any={};installBackupIpc(window,backend,'workbench://desktop/index.html');
    expect(()=>validateCall('storage.backup.create',{path:'C:/secret'})).toThrow();
    await expect(handlers.get('storage.backup.create')({...event,sender:{}},{})).rejects.toThrow();
    expect(dialog.showSaveDialog).not.toHaveBeenCalled();
  });
  it('writes downloaded bytes once and never overwrites an existing save',async()=>{
    const root=await mkdtemp(join(tmpdir(),'backup-ipc-'));const path=join(root,'backup.zip');
    dialog.showSaveDialog.mockResolvedValue({canceled:false,filePath:path});
    const backend:any={request:vi.fn().mockResolvedValue({backup_id:'safe_id',verified:true,files_verified:3}),response:vi.fn().mockImplementation(()=>Promise.resolve(new Response(new Uint8Array([80,75,1]),{headers:{'Content-Type':'application/zip','X-Content-SHA256':createHash('sha256').update(new Uint8Array([80,75,1])).digest('hex')}})))};
    installBackupIpc(window,backend,'workbench://desktop/index.html');
    const result=await handlers.get('storage.backup.create')(event,{});
    expect(result.saved).toBe(true);expect(await readFile(path)).toEqual(Buffer.from([80,75,1]));
    await expect(handlers.get('storage.backup.create')(event,{})).rejects.toThrow();
    expect(await readFile(path)).toEqual(Buffer.from([80,75,1]));
  });
  it('confirms validated selected bytes, then switches via the managed restart',async()=>{
    const root=await mkdtemp(join(tmpdir(),'restore-ipc-'));const path=join(root,'backup.zip');await writeFile(path,new Uint8Array([80,75,1]));
    dialog.showOpenDialog.mockResolvedValue({canceled:false,filePaths:[path]});dialog.showMessageBox.mockResolvedValue({response:1});
    const backend:any={response:vi.fn().mockResolvedValue(Response.json({backup_id:'imported',verified:true,schema_version:4,files_verified:2,size_bytes:100})),request:vi.fn().mockResolvedValue({verified:true,restart_required:true,source_retained:true,destination:join(root,'restored'),files_verified:2,credential_restored:false,reconnect_required:true}),relocateTo:vi.fn().mockResolvedValue(undefined)};
    const persist=vi.fn();installBackupIpc(window,backend,'workbench://desktop/index.html',persist);
    const result=await handlers.get('storage.backup.restore')(event,{});
    expect(backend.response.mock.calls[0][2]).toEqual(Buffer.from([80,75,1]));
    expect(backend.relocateTo).toHaveBeenCalledWith(join(root,'restored'),persist);
    expect(result.restored).toBe(true);expect(result.restart_required).toBe(false);
    expect(result.destination).toBeUndefined();
  });
  it('cancelled confirmation never invokes restore or restart',async()=>{
    const root=await mkdtemp(join(tmpdir(),'restore-cancel-'));const path=join(root,'backup.zip');await writeFile(path,new Uint8Array([80,75]));
    dialog.showOpenDialog.mockResolvedValue({canceled:false,filePaths:[path]});dialog.showMessageBox.mockResolvedValue({response:0});
    const backend:any={response:vi.fn().mockResolvedValue(Response.json({backup_id:'imported',verified:true,schema_version:4,files_verified:2,size_bytes:100})),request:vi.fn(),relocateTo:vi.fn()};
    installBackupIpc(window,backend,'workbench://desktop/index.html');
    expect((await handlers.get('storage.backup.restore')(event,{})).cancelled).toBe(true);
    expect(backend.request).not.toHaveBeenCalled();expect(backend.relocateTo).not.toHaveBeenCalled();
  });
});
