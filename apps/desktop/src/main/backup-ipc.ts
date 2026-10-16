import { ipcMain, dialog, type BrowserWindow } from 'electron';
import { lstat, open } from 'node:fs/promises';
import { isAbsolute } from 'node:path';
import type { BackendSupervisor } from './backend';
import { isTrustedSender, validateCall, id } from '../shared/validation';
import { saveFilesAtomically, verifyBytes } from './artifact-files';

const channels=['storage.backup.create','storage.backup.restore'] as const;
const maxBytes=256*1024*1024;
export function installBackupIpc(window:BrowserWindow,backend:BackendSupervisor,url:string,persist?:(destination:string)=>Promise<void>) {
  for(const channel of channels)ipcMain.handle(channel,async(event,input)=>{
    if(!isTrustedSender(event,window,url))throw new Error('请求来源不受支持。');
    validateCall(channel,input);
    try {
      if(channel==='storage.backup.create') {
        const selection=await dialog.showSaveDialog(window,{title:'保存一致性备份',defaultPath:'workbench-backup.zip',filters:[{name:'工作台备份',extensions:['zip']}]});
        if(selection.canceled||!selection.filePath)return {cancelled:true,saved:false};
        const created=await backend.request<any>('/v1/backups','POST',{},120000);
        if(created.verified!==true)throw new Error('备份尚未核验。');
        const backupId=id(created.backup_id);
        const response=await backend.response(`/v1/backups/${backupId}/download`,'GET',undefined,120000);
        if(!response.headers.get('Content-Type')?.includes('application/zip'))throw new Error('备份格式不受支持。');
        const bytes=new Uint8Array(await response.arrayBuffer());
        if(bytes.length>maxBytes)throw new Error('备份超过 256 MB 上限。');
        verifyBytes(bytes,response.headers.get('X-Content-SHA256')??'');
        await saveFilesAtomically([{path:selection.filePath,bytes}]);
        return {cancelled:false,saved:true,files_verified:created.files_verified,size_bytes:bytes.length};
      }
      const selection=await dialog.showOpenDialog(window,{title:'选择工作台备份',properties:['openFile'],filters:[{name:'工作台备份',extensions:['zip']}]});
      if(selection.canceled||selection.filePaths.length!==1)return {cancelled:true,restored:false};
      const selected=selection.filePaths[0];
      const observed=await lstat(selected);
      if(!observed.isFile()||observed.isSymbolicLink()||observed.nlink!==1||observed.size>maxBytes)throw new Error('备份文件类型或大小不受支持。');
      const handle=await open(selected,'r');
      let bytes:Buffer;
      try{const current=await handle.stat();if(current.dev!==observed.dev||current.ino!==observed.ino||current.size!==observed.size)throw new Error('备份文件已改变，请重新选择。');bytes=await handle.readFile();}finally{await handle.close();}
      if(bytes.length!==observed.size)throw new Error('备份文件已改变，请重新选择。');
      const importedResponse=await backend.response('/v1/backups/import','POST',bytes,120000,{'Content-Type':'application/zip'});
      const imported=await importedResponse.json();
      if(imported.verified!==true)throw new Error('备份尚未核验。');
      const backupId=id(imported.backup_id);
      const confirmation=await dialog.showMessageBox(window,{type:'question',title:'恢复已核验备份',message:`已核验 ${imported.files_verified} 个文件，数据库版本 ${imported.schema_version}。`,detail:'确认后将在独立目录恢复并重新连接本地服务。当前目录会保留。备份不含连接凭证，恢复后请重新核验模型连接。',buttons:['取消','恢复并重新连接'],defaultId:0,cancelId:0,noLink:true});
      if(confirmation.response!==1)return {cancelled:true,restored:false};
      const result=await backend.request<any>(`/v1/backups/${backupId}/restore`,'POST',{},120000);
      if(result.verified!==true||result.source_retained!==true||typeof result.destination!=='string'||!isAbsolute(result.destination))throw new Error('恢复副本尚未核验，原目录保留。');
      await backend.relocateTo(result.destination,persist);
      return {cancelled:false,restored:true,verified:true,restart_required:false,source_retained:true,
        files_verified:result.files_verified,credential_restored:false,reconnect_required:true};
    }catch(error){throw new Error(error instanceof Error&&/[\u4e00-\u9fff]/.test(error.message)?error.message:'备份操作未完成，原目录保留。请检查文件、空间和任务状态。');}
  });
  return ()=>{for(const channel of channels)ipcMain.removeHandler(channel);};
}
