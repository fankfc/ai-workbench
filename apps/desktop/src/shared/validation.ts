export type RecordValue = Record<string, unknown>;
export function record(value: unknown): RecordValue {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('请求字段不符合接口要求。');
  return value as RecordValue;
}
export function exact(value: RecordValue, keys: string[]) {
  if (Object.keys(value).some(key => !keys.includes(key))) throw new Error('请求字段不符合接口要求。');
}
export function string(value: unknown, max = 128): string {
  if (typeof value !== 'string' || !value.trim() || value.length > max) throw new Error('请求字段不符合接口要求。');
  return value;
}
export function id(value: unknown): string {
  const result = string(value);
  if (!/^[a-zA-Z0-9_-]+$/.test(result)) throw new Error('请求字段不符合接口要求。');
  return result;
}
export function acceptHandshake(value: unknown, identity: string, pid: number): boolean {
  try {
    const v = record(value);
    return v.kind === 'backend.ready' && v.instance_id === identity && v.pid === pid && v.protocol_version === '1.0' && Number.isInteger(v.port) && Number(v.port) > 0 && Number(v.port) < 65536;
  } catch { return false; }
}
export function isTrustedSender(event: any, window: any, url: string): boolean {
  return event.sender === window.webContents && event.senderFrame === window.webContents.mainFrame && event.senderFrame?.url?.split('#')[0] === url;
}
export function validateCall(method: string, value: unknown): RecordValue {
  const v = record(value);
  const empty = ['status','getSettings','getStorage','exportDiagnostics','retryBackend','previewRelocation','getExportDirectory','chooseExportDirectory','clearExportDirectory','storage.backup.create','storage.backup.restore'];
  if (empty.includes(method)) { exact(v, []); return v; }
  if (['createConversation'].includes(method)) { exact(v,['title']); string(v.title,200); return v; }
  if (method === 'listConversations') {
    exact(v,['query','archived','offset']);
    if (v.query !== undefined && (typeof v.query !== 'string' || v.query.length > 200)) throw new Error('搜索内容过长。');
    if (v.archived !== undefined && typeof v.archived !== 'boolean') throw new Error('归档参数无效。');
    if (v.offset !== undefined && (!Number.isInteger(v.offset) || Number(v.offset) < 0)) throw new Error('分页参数无效。');
    return v;
  }
  if (method === 'updateConversation') {
    exact(v,['conversationId','title','pinned','archived','expected_version']); id(v.conversationId);
    if(v.title !== undefined) string(v.title,200);
    for(const key of ['pinned','archived']) if(v[key] !== undefined && typeof v[key] !== 'boolean') throw new Error('更新参数无效。');
    if(v.expected_version !== undefined && (!Number.isInteger(v.expected_version) || Number(v.expected_version)<1)) throw new Error('版本无效。');
    return v;
  }
  if (['listMessages','chooseFiles','listAttachments','listArtifacts','subscribePublic','deleteConversation'].includes(method)) {
    exact(v,method === 'subscribePublic' ? ['conversationId','afterSeq'] : ['conversationId']); id(v.conversationId);
    if(method === 'subscribePublic' && (!Number.isInteger(v.afterSeq) || Number(v.afterSeq)<0)) throw new Error('事件游标无效。');
    return v;
  }
  if(method === 'removeAttachment') { exact(v,['conversationId','attachmentId']); id(v.conversationId); id(v.attachmentId); return v; }
  if (method === 'submitTurn') {
    exact(v,['conversationId','text','provider_profile_id','client_request_id','connection_version','attachment_ids','domain','profile_inputs']);
    id(v.conversationId); string(v.text,65536); id(v.provider_profile_id); id(v.client_request_id); string(v.connection_version);
    if(!['code','paper','document','mixed'].includes(String(v.domain))) throw new Error('任务类型无效。');
    if(!Array.isArray(v.attachment_ids) || v.attachment_ids.length>20) throw new Error('附件参数无效。');
    v.attachment_ids.forEach(id);
    if(v.profile_inputs!==undefined){const p=record(v.profile_inputs);const allowed:Record<string,string[]>={document:['audience','purpose','source_refs','formats'],paper:['research_question','evidence_refs','data_refs','formats'],code:['requirements','test_command','workspace_ref'],mixed:['data_refs','formats']};exact(p,allowed[String(v.domain)]);
      const ref=(value:unknown)=>{const path=string(value,256);if(path==='input/user_request.txt'&&v.domain==='document')return;const matched=/^input\/attachment_([a-zA-Z0-9_-]+)\.(md|txt|csv|json|pdf|docx)$/.exec(path);if(!matched||!(v.attachment_ids as string[]).includes(matched[1]))throw new Error('材料引用不属于本次任务。');};
      for(const [key,value] of Object.entries(p)){if(['source_refs','evidence_refs','data_refs'].includes(key)){if(!Array.isArray(value)||value.length>20)throw new Error('材料引用数量无效。');value.forEach(ref);}else if(key==='workspace_ref')ref(value);else if(key==='formats'){if(!Array.isArray(value)||value.length>3||new Set(value).size!==value.length||value.some(item=>!['pdf','docx','markdown'].includes(String(item))))throw new Error('文件格式无效。');}else {string(value,key==='test_command'?1024:8192);if(key==='test_command'&&/[\r\n\0]/.test(String(value)))throw new Error('测试命令需为单行项目说明。');}}
      if(JSON.stringify(p).length>32768)throw new Error('任务资料过长。');
    }return v;
  }
  if(method === 'cancelTurn' || method === 'getTask') { exact(v,['taskId']); id(v.taskId); return v; }
  if(method === 'probeConnection') { exact(v,['connectionId']); id(v.connectionId); return v; }
  if(method === 'updatePreferences') {
    exact(v,['expected_version','preferences']);
    if(!Number.isInteger(v.expected_version) || Number(v.expected_version)<1) throw new Error('偏好版本无效。');
    const p=record(v.preferences); exact(p,['theme','font_size','send_shortcut','close_behavior']);
    if(!['system','light','dark'].includes(String(p.theme)) || !['enter','ctrl-enter'].includes(String(p.send_shortcut)) || !['quit','minimize'].includes(String(p.close_behavior)) || !Number.isInteger(p.font_size) || Number(p.font_size)<14 || Number(p.font_size)>22) throw new Error('偏好参数无效。');
    return v;
  }
  if(method === 'getUsage') {
    exact(v,['role','function','task_id','offset','date_from','date_to']);
    for(const key of ['role','function','date_from','date_to']) if(v[key]!==undefined) string(v[key],64);
    if(v.task_id!==undefined) id(v.task_id);
    if(v.offset!==undefined && (!Number.isInteger(v.offset) || Number(v.offset)<0)) throw new Error('分页参数无效。');
    return v;
  }
  if(method === 'previewCleanup') { exact(v,[]); return v; }
  if(method === 'relocateStorage') {exact(v,['version']);string(v.version,256);return v;}
  if(method === 'cleanupStorage') { exact(v,['version','sha256s']); string(v.version); if(!Array.isArray(v.sha256s) || v.sha256s.length>10000 || v.sha256s.some(hash=>typeof hash!=='string' || !/^[a-f0-9]{64}$/.test(hash))) throw new Error('清理版本无效。'); return v; }
  if(['previewArtifact','saveArtifact','saveArtifactPair'].includes(method)) {
    exact(v,['conversationId','bundleId','artifactIds']); id(v.conversationId); id(v.bundleId);
    if(!Array.isArray(v.artifactIds) || v.artifactIds.length !== (method==='saveArtifactPair'?2:1)) throw new Error('文件选择无效。');
    v.artifactIds.forEach(id); return v;
  }
  throw new Error('不支持该桌面操作。');
}
