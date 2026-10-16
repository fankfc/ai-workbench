import { contextBridge, ipcRenderer } from 'electron';
import type { DesktopBridge } from '../shared/desktop-bridge';
import { backupBridge } from './backup';
const call=(method:string,input:unknown={})=>ipcRenderer.invoke(`workbench:${method}`,input);
const bridge:DesktopBridge={
  ...backupBridge,
  status:()=>call('status'),retryBackend:()=>call('retryBackend'),
  createConversation:input=>call('createConversation',input),listConversations:input=>call('listConversations',input),updateConversation:input=>call('updateConversation',input),deleteConversation:input=>call('deleteConversation',input),
  listMessages:input=>call('listMessages',input),submitTurn:input=>call('submitTurn',input),cancelTurn:input=>call('cancelTurn',input),getTask:input=>call('getTask',input),
  chooseFiles:input=>call('chooseFiles',input),listAttachments:input=>call('listAttachments',input),removeAttachment:input=>call('removeAttachment',input),
  listArtifacts:input=>call('listArtifacts',input),previewArtifact:input=>call('previewArtifact',input),saveArtifact:input=>call('saveArtifact',input),saveArtifactPair:input=>call('saveArtifactPair',input),
  getSettings:()=>call('getSettings'),updatePreferences:input=>call('updatePreferences',input),probeConnection:input=>call('probeConnection',input),
  getUsage:input=>call('getUsage',input),getStorage:()=>call('getStorage'),previewCleanup:()=>call('previewCleanup'),cleanupStorage:input=>call('cleanupStorage',input),exportDiagnostics:()=>call('exportDiagnostics'),
  previewRelocation:()=>call('previewRelocation'),relocateStorage:input=>call('relocateStorage',input),
  getExportDirectory:()=>call('getExportDirectory'),chooseExportDirectory:()=>call('chooseExportDirectory'),clearExportDirectory:()=>call('clearExportDirectory'),
  subscribePublic:(input,listener)=>{
    const receive=(_event:unknown,frame:any)=>{if(frame?.conversation_id===input.conversationId)listener(frame);};
    ipcRenderer.on('workbench:public',receive);call('subscribePublic',input).catch(()=>{});
    return ()=>{ipcRenderer.removeListener('workbench:public',receive);call('unsubscribePublic',{conversationId:input.conversationId}).catch(()=>{});};
  }
};
contextBridge.exposeInMainWorld('workbench',Object.freeze(bridge));
