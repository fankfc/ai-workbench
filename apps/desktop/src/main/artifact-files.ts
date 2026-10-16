import { dialog, type BrowserWindow } from 'electron';
import { createHash, randomUUID } from 'node:crypto';
import { basename, dirname, join } from 'node:path';
import { open, access, unlink, link } from 'node:fs/promises';
import { constants } from 'node:fs';
import type { ArtifactRequest, Bundle, SaveResult } from '../shared/desktop-bridge';
import type { BackendSupervisor } from './backend';
export function safeFilename(name:string) {
  if(!name || basename(name)!==name || /[<>:"/\\|?*\x00-\x1f]/.test(name) || /[. ]$/.test(name) || /^(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\.|$)/i.test(name))throw new Error('文件名称不受支持。');
  return name;
}
export function verifyBytes(bytes:Uint8Array,expected:string) {
  if(!/^[a-f0-9]{64}$/.test(expected) || createHash('sha256').update(bytes).digest('hex')!==expected)throw new Error('文件检查失败，暂时无法保存。');
}
export async function saveFilesAtomically(files:{path:string;bytes:Uint8Array}[],operations:{link:typeof link;unlink:typeof unlink}={link,unlink}):Promise<string[]> {
  const temporary:string[]=[]; const saved:string[]=[];
  try {
    if(new Set(files.map(file=>file.path.toLocaleLowerCase())).size!==files.length)throw new Error('文件名称重复，请选择其他位置。');
    for(const file of files) {
      await access(dirname(file.path),constants.W_OK);
      try{await access(file.path);throw new Error('同名文件已存在，请选择其他位置。');}catch(error:any){if(error.code!=='ENOENT')throw error;}
      const temp=join(dirname(file.path),`.workbench-${randomUUID()}.tmp`);temporary.push(temp);
      const handle=await open(temp,'wx');try{await handle.writeFile(file.bytes);await handle.sync();}finally{await handle.close();}
    }
    for(let index=0;index<files.length;index++){await operations.link(temporary[index],files[index].path);saved.push(files[index].path);}
    return saved.map(path=>basename(path));
  } catch(error) {
    const remaining:string[]=[];
    for(const path of saved){try{await operations.unlink(path);}catch{remaining.push(basename(path));}}
    if(remaining.length)throw new Error(`双语文件保存未完整完成。无法撤回的文件仍已保存：${remaining.join('、')}。请检查目标目录后重试。`);
    if(error instanceof Error && /[\u4e00-\u9fff]/.test(error.message))throw error;
    throw new Error('保存失败，请检查目录空间和权限后重试。本次文件未保存。');
  } finally{for(const temp of temporary)await unlink(temp).catch(()=>{});}
}
export class ArtifactFiles {
  constructor(private backend:BackendSupervisor,private window:BrowserWindow,private defaultDirectory:()=>string|undefined=()=>undefined){}
  async selected(input:ArtifactRequest) {
    const page=await this.backend.request<{items:Bundle[]}>(`/v1/conversations/${input.conversationId}/bundles`);
    const bundle=page.items.find(value=>value.bundle_id===input.bundleId);
    if(!bundle)throw new Error('该文件组尚未发布或已失效。');
    const artifacts=input.artifactIds.map(identity=>bundle.artifacts.find(value=>value.artifact_id===identity));
    if(artifacts.some(value=>!value))throw new Error('文件不属于当前会话。');
    if(artifacts.length===2 && (!artifacts[0]!.artifact_pair_id || artifacts[0]!.artifact_pair_id!==artifacts[1]!.artifact_pair_id || artifacts[0]!.language===artifacts[1]!.language || artifacts[0]!.format!==artifacts[1]!.format))throw new Error('双语文件版本不一致。');
    return artifacts.map(value=>value!);
  }
  async save(input:ArtifactRequest):Promise<SaveResult> {
    const artifacts=await this.selected(input);
    let paths:string[];
    if(artifacts.length===2){const selection=await dialog.showOpenDialog(this.window,{title:'保存同一版本的两份文件',defaultPath:this.defaultDirectory(),properties:['openDirectory','createDirectory']});if(selection.canceled)return {cancelled:true,saved:[]};paths=artifacts.map(artifact=>join(selection.filePaths[0],safeFilename(artifact.file_name)));}
    else {const filename=safeFilename(artifacts[0].file_name);const directory=this.defaultDirectory();const selection=await dialog.showSaveDialog(this.window,{title:'保存文件',defaultPath:directory?join(directory,filename):filename});if(selection.canceled || !selection.filePath)return {cancelled:true,saved:[]};paths=[selection.filePath];}
    const files=[];
    for(let index=0;index<artifacts.length;index++){
      const artifact=artifacts[index];const response=await this.backend.response(`/v1/conversations/${input.conversationId}/bundles/${input.bundleId}/artifacts/${artifact.artifact_id}/download`);
      if(artifact.size_bytes>128*1024*1024)throw new Error('文件过大，暂时无法保存。');
      const bytes=new Uint8Array(await response.arrayBuffer());
      if(bytes.length!==artifact.size_bytes)throw new Error('文件检查失败，暂时无法保存。');
      verifyBytes(bytes,artifact.sha256??response.headers.get('X-Content-SHA256')??'');files.push({path:paths[index],bytes});
    }
    const saved=await saveFilesAtomically(files);return {cancelled:false,saved};
  }
  async preview(input:ArtifactRequest) {
    const [artifact]=await this.selected(input);
    try {
      const response=await this.backend.response(`/v1/conversations/${input.conversationId}/bundles/${input.bundleId}/artifacts/${artifact.artifact_id}/preview`);
      const contentType=response.headers.get('Content-Type')??'';const bytes=new Uint8Array(await response.arrayBuffer());
      if(bytes.length>20*1024*1024)throw new Error('预览内容过大，请保存后打开。');
      if(contentType.startsWith('text/plain'))return {available:true,format:'md',language:artifact.language,text:new TextDecoder('utf-8',{fatal:true}).decode(bytes)};
      if(contentType.startsWith('application/pdf') && Buffer.from(bytes.subarray(0,5)).toString()==='%PDF-')return {available:true,format:'pdf',language:artifact.language,data:Buffer.from(bytes).toString('base64')};
      return {available:false,format:artifact.format,language:artifact.language,message:'暂时无法预览，可保存后打开。'};
    }catch(error){return {available:false,format:artifact.format,language:artifact.language,message:error instanceof Error && /[\u4e00-\u9fff]/.test(error.message)?error.message:'暂时无法预览，可保存后打开。'};}
  }
}
