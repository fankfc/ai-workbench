import { dialog, type BrowserWindow } from 'electron';
import { basename } from 'node:path';
import { stat, readFile } from 'node:fs/promises';
import type { BackendSupervisor } from './backend';
import type { Attachment } from '../shared/desktop-bridge';
export async function chooseFiles(window:BrowserWindow,backend:BackendSupervisor,conversation:string):Promise<Attachment[]> {
  const result=await dialog.showOpenDialog(window,{title:'添加任务材料',properties:['openFile','multiSelections'],filters:[{name:'任务材料',extensions:['txt','md','pdf','docx','csv','json']}]});
  if(result.canceled)return [];
  if(result.filePaths.length>20)throw new Error('一次最多添加 20 个文件。');
  const imported:Attachment[]=[];
  for(const path of result.filePaths){
    const metadata=await stat(path);if(!metadata.isFile() || metadata.size>20*1024*1024)throw new Error('文件过大或无法读取。每个文件上限为 20 MB。');
    const bytes=new Uint8Array(await readFile(path));
    const response=await backend.response(`/v1/conversations/${conversation}/attachments`,'POST',bytes,15000,{'Content-Type':'application/octet-stream','X-Filename':encodeURIComponent(basename(path))});
    imported.push(await response.json());
  }
  return imported;
}
