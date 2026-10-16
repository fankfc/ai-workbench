import { ipcMain, dialog, type BrowserWindow } from 'electron';
import { writeFile } from 'node:fs/promises';
import type { BackendSupervisor } from './backend';
import { isTrustedSender, validateCall } from '../shared/validation';
import { parsePublicEvent } from '../renderer/chat/public-events';
import { chooseFiles } from './attachments';
import { ArtifactFiles } from './artifact-files';
import type { ExportDirectory } from './export-directory';
import { installBackupIpc } from './backup-ipc';
export function installIpc(window:BrowserWindow,backend:BackendSupervisor,url:string,onPreferences:(settings:any)=>void,onFrame?:(frame:any)=>void,onRelocation?:(destination:string)=>Promise<void>,exports?:ExportDirectory) {
  const removeBackupIpc=installBackupIpc(window,backend,url,onRelocation);
  const artifactFiles=new ArtifactFiles(backend,window,()=>exports?.path);const subscriptions=new Map<string,{cursor:number;timer?:ReturnType<typeof setTimeout>;closed:boolean}>();
  const methods=['status','retryBackend','createConversation','listConversations','updateConversation','deleteConversation','listMessages','submitTurn','cancelTurn','getTask','chooseFiles','listAttachments','removeAttachment','listArtifacts','previewArtifact','saveArtifact','saveArtifactPair','getSettings','updatePreferences','probeConnection','getUsage','getStorage','previewCleanup','cleanupStorage','exportDiagnostics','subscribePublic','unsubscribePublic','previewRelocation','relocateStorage','getExportDirectory','chooseExportDirectory','clearExportDirectory'];
  const relocations=new Map<string,string>();
  const route=(v:any)=>`/v1/conversations/${v.conversationId}`;
  const startSubscription=(v:any)=>{
    const existing=subscriptions.get(v.conversationId);if(existing){existing.closed=true;clearTimeout(existing.timer);}
    const subscription={cursor:v.afterSeq,closed:false,timer:undefined as ReturnType<typeof setTimeout>|undefined};subscriptions.set(v.conversationId,subscription);
    const poll=async()=>{
      if(subscription.closed || window.isDestroyed())return;
      try{const response=await backend.response(`${route(v)}/events?after_seq=${subscription.cursor}`);const text=await response.text();
        for(const block of text.split(/\r?\n\r?\n/)){const data=block.split(/\r?\n/).filter(line=>line.startsWith('data:')).map(line=>line.slice(5).trim()).join('\n');if(!data)continue;try{const frame=parsePublicEvent(JSON.parse(data));if(frame && frame.conversation_id===v.conversationId && frame.sequence>subscription.cursor){subscription.cursor=frame.sequence;onFrame?.(frame);if(!subscription.closed&&!window.isDestroyed())window.webContents.send('workbench:public',frame);}}catch{}}
      }catch{}finally{if(!subscription.closed)subscription.timer=setTimeout(poll,250);}
    };void poll();return {subscribed:true};
  };
  for(const method of methods)ipcMain.handle(`workbench:${method}`,async(event,input)=>{
    if(!isTrustedSender(event,window,url))throw new Error('请求来源不受支持。');
    const v=validateCall(method==='unsubscribePublic'?'listMessages':method,input);
    try {
      switch(method){
        case 'status':return backend.status;
        case 'retryBackend':return await backend.start();
        case 'createConversation':return await backend.request('/v1/conversations','POST',v);
        case 'listConversations':{const query=new URLSearchParams({query:String(v.query??''),archived:String(v.archived??false),offset:String(v.offset??0)});return await backend.request(`/v1/conversations?${query}`);}
        case 'updateConversation':{const {conversationId,...body}=v;return await backend.request(route(v),'PATCH',body);}
        case 'deleteConversation':return await backend.request(route(v),'DELETE');
        case 'listMessages':return await backend.request(`${route(v)}/messages`);
        case 'submitTurn':{const {conversationId,...body}=v;if(v.profile_inputs){const refs=Object.entries(v.profile_inputs as Record<string,unknown>).filter(([key])=>key.endsWith('_ref')||key.endsWith('_refs')).flatMap(([,value])=>Array.isArray(value)?value:[value]).filter(value=>value!=='input/user_request.txt');if(refs.length){const page=await backend.request<any>(`${route(v)}/attachments`);const allowed=new Set(page.items.filter((file:any)=>file.status==='ready'&&(v.attachment_ids as string[]).includes(file.id)).map((file:any)=>`input/attachment_${file.id}.${file.name.split('.').at(-1).toLowerCase()}`));if(refs.some(ref=>!allowed.has(ref)))throw new Error('材料引用与所选文件不一致，请重新选择。');}}return await backend.request(`${route(v)}/turns`,'POST',body);}
        case 'cancelTurn':return await backend.request(`/v1/tasks/${v.taskId}/cancel`,'POST',{});
        case 'getTask':return await backend.request(`/v1/tasks/${v.taskId}`);
        case 'chooseFiles':return await chooseFiles(window,backend,String(v.conversationId));
        case 'listAttachments':return await backend.request(`${route(v)}/attachments`);
        case 'removeAttachment':return await backend.request(`${route(v)}/attachments/${v.attachmentId}`,'DELETE');
        case 'listArtifacts':return await backend.request(`${route(v)}/bundles`);
        case 'previewArtifact':return await artifactFiles.preview(v as any);
        case 'saveArtifact':case 'saveArtifactPair':return await artifactFiles.save(v as any);
        case 'getSettings':{const settings=await backend.request('/v1/settings');onPreferences(settings);return settings;}
        case 'updatePreferences':{const settings=await backend.request('/v1/settings','PATCH',v);onPreferences(settings);return settings;}
        case 'probeConnection':return await backend.request(`/v1/settings/connections/${v.connectionId}/probe`,'POST',{});
        case 'getUsage':return await backend.request(`/v1/usage?${new URLSearchParams(Object.entries(v).map(([key,value])=>[key,String(value)]))}`);
        case 'getStorage':return await backend.request('/v1/storage');
        case 'getExportDirectory':return exports?.status??{configured:false,label:'每次保存时选择'};
        case 'chooseExportDirectory':{if(!exports)throw new Error('目录偏好暂不可用。');const selection=await dialog.showOpenDialog(window,{title:'选择默认导出目录',defaultPath:exports.path,properties:['openDirectory','createDirectory']});if(selection.canceled)return exports.status;return await exports.set(selection.filePaths[0]);}
        case 'clearExportDirectory':{if(!exports)throw new Error('目录偏好暂不可用。');return await exports.set();}
        case 'previewRelocation':{const selection=await dialog.showOpenDialog(window,{title:'选择新的本地存储目录',properties:['openDirectory','createDirectory']});if(selection.canceled)return {cancelled:true};const destination=selection.filePaths[0];const preview=await backend.request<any>('/v1/storage/relocation-preview','POST',{destination});relocations.clear();relocations.set(preview.version,destination);return {cancelled:false,version:preview.version,ready:preview.ready,files:preview.files,required_bytes:preview.required_bytes,source_retained:preview.source_retained};}
        case 'relocateStorage':{const destination=relocations.get(String(v.version));if(!destination)throw new Error('目录选择已失效，请重新预检。');const result=await backend.request<any>('/v1/storage/relocate','POST',v);if(result.verified!==true)throw new Error('目录迁移尚未核验。');await backend.relocateTo(destination,onRelocation);relocations.delete(String(v.version));return {verified:true,restart_required:false,source_retained:result.source_retained,files_verified:result.files_verified};}
        case 'previewCleanup':return await backend.request('/v1/storage/cleanup-preview','POST',{});
        case 'cleanupStorage':return await backend.request('/v1/storage/cleanup','POST',v);
        case 'exportDiagnostics':{const selection=await dialog.showSaveDialog(window,{title:'保存脱敏诊断',defaultPath:'workbench-diagnostics.zip'});if(selection.canceled||!selection.filePath)return {cancelled:true,saved:[]};const response=await backend.response('/v1/diagnostics/export','POST',{});if(!response.headers.get('Content-Type')?.includes('application/zip'))throw new Error('诊断导出格式暂不可用。');await writeFile(selection.filePath,Buffer.from(await response.arrayBuffer()),{flag:'wx'});return {cancelled:false,saved:['workbench-diagnostics.zip']};}
        case 'subscribePublic':return startSubscription(v);
        case 'unsubscribePublic':{const subscription=subscriptions.get(String(v.conversationId));if(subscription){subscription.closed=true;clearTimeout(subscription.timer);subscriptions.delete(String(v.conversationId));}return {subscribed:false};}
      }
    }catch(error){throw new Error(error instanceof Error && /[\u4e00-\u9fff]/.test(error.message)?error.message:'操作暂未完成，请重试。');}
  });
  return ()=>{removeBackupIpc();for(const subscription of subscriptions.values()){subscription.closed=true;clearTimeout(subscription.timer);}for(const method of methods)ipcMain.removeHandler(`workbench:${method}`);};
}
