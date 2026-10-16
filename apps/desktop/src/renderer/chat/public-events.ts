import { exact, id, record, string } from '../../shared/validation';
export type PublicFrame={schema_version:string;event_id:string;conversation_id:string;turn_id:string;task_id:string;attempt_id:string;sequence:number;kind:string;payload:Record<string,any>};
const fields:Record<string,string[]>={
  'message.accepted':['message_id','text','language'], 'response.pending':['status'],
  'answer.published':['message_id','text','language','content_version_id','approval_id'],
  'artifacts.published':['bundle_id','version_id','artifacts'], 'request.failed':['error_code','text','language','action'],
  'request.cancelled':['text','language','cancel_requested','external_stop_confirmed'], 'input.required':['prompt_id','text','language']
};
export function parsePublicEvent(value: unknown): PublicFrame|null {
  try {
    const v=record(value); exact(v,['schema_version','event_id','conversation_id','turn_id','task_id','attempt_id','sequence','kind','payload']);
    if(v.schema_version!=='1.0' || !Number.isInteger(v.sequence) || Number(v.sequence)<1 || typeof v.kind!=='string' || !fields[v.kind]) return null;
    for(const key of ['event_id','conversation_id','turn_id','task_id','attempt_id']) id(v[key]);
    const p=record(v.payload); exact(p,fields[v.kind]);
    if(Object.keys(p).length!==fields[v.kind].length) return null;
    if(v.kind==='response.pending') {if(p.status!=='pending') return null;}
    else if(v.kind==='artifacts.published') {
      id(p.bundle_id); id(p.version_id);
      if(!Array.isArray(p.artifacts) || !p.artifacts.length) return null;
      for(const artifact of p.artifacts) {const a=record(artifact);exact(a,['artifact_id','artifact_pair_id','format','language','file_name','size_bytes']);id(a.artifact_id);if(a.artifact_pair_id!==null)id(a.artifact_pair_id);for(const key of ['format','language','file_name'])string(a[key],256);if(!Number.isInteger(a.size_bytes)||Number(a.size_bytes)<0)return null;}
    } else {
      string(p.text,1_048_576); string(p.language,32);
      if(['request.failed','request.cancelled'].includes(v.kind) && p.language!=='zh-CN') return null;
      if(v.kind==='input.required'&&!['zh-CN','en'].includes(String(p.language)))return null;
      if(v.kind==='request.cancelled' && (p.cancel_requested!==true || (p.external_stop_confirmed!==null && typeof p.external_stop_confirmed!=='boolean'))) return null;
      if(v.kind==='request.failed' && !['retry','reconnect','provide_input','none'].includes(String(p.action)))return null;
      for(const key of ['message_id','content_version_id','approval_id','prompt_id','error_code'])if(p[key]!==undefined)id(p[key]);
    }
    return v as PublicFrame;
  } catch { return null; }
}
export type Run={turnId:string;taskId:string;attemptId:string;status:'pending'|'stopping'|'cancelled'|'completed'|'failed'|'needs_input';confirmed:boolean|null};
export type PublicState={cursor:number;seen:Set<string>;messages:any[];runs:Record<string,Run>;bundles:any[];notice:string};
export function emptyPublicState():PublicState {return {cursor:0,seen:new Set(),messages:[],runs:{},bundles:[],notice:''};}
export function acceptReceipt(state:PublicState,receipt:{turn_id:string;task_id:string}):PublicState {
  if(state.runs[receipt.turn_id])return state;
  const terminal=state.messages.find(message=>message.turn_id===receipt.turn_id&&['answer.published','request.failed','request.cancelled','input.required'].includes(message.kind));
  const status:Run['status']=terminal?({'answer.published':'completed','request.failed':'failed','request.cancelled':'cancelled','input.required':'needs_input'} as const)[terminal.kind as 'answer.published']:'pending';
  return {...state,runs:{...state.runs,[receipt.turn_id]:{turnId:receipt.turn_id,taskId:receipt.task_id,attemptId:terminal?.attempt_id??'',status,confirmed:null}}};
}
export function reducePublic(state:PublicState, event:unknown, conversationId:string):PublicState {
  const e=parsePublicEvent(event);
  if(!e || e.conversation_id!==conversationId || state.seen.has(e.event_id) || e.sequence<=state.cursor)return state;
  const next={...state,cursor:e.sequence,seen:new Set([...state.seen,e.event_id]),messages:[...state.messages],runs:{...state.runs},bundles:[...state.bundles]};
  const current=next.runs[e.turn_id]; const p=e.payload;
  if(e.kind==='message.accepted' && !next.messages.some(m=>m.id===p.message_id))next.messages.push({id:p.message_id,turn_id:e.turn_id,kind:e.kind,text:p.text,language:p.language,historical:false,attempt_id:e.attempt_id});
  if(e.kind==='response.pending' && !['cancelled','completed'].includes(current?.status))next.runs[e.turn_id]={turnId:e.turn_id,taskId:e.task_id,attemptId:e.attempt_id,status:'pending',confirmed:null};
  if(e.kind==='request.cancelled') {next.runs[e.turn_id]={turnId:e.turn_id,taskId:e.task_id,attemptId:e.attempt_id,status:'cancelled',confirmed:p.external_stop_confirmed};next.notice=p.external_stop_confirmed===true?'已停止，已保存当前进度。':'取消请求已记录，正在等待停止确认。';}
  if(e.kind==='answer.published' && current?.status!=='cancelled' && current?.status!=='stopping') {if(!next.messages.some(m=>m.id===p.message_id))next.messages.push({id:p.message_id,turn_id:e.turn_id,kind:e.kind,text:p.text,language:p.language,historical:false,attempt_id:e.attempt_id,content_version_id:p.content_version_id});next.runs[e.turn_id]={turnId:e.turn_id,taskId:e.task_id,attemptId:e.attempt_id,status:'completed',confirmed:null};next.notice='新回答已完成。';}
  if(e.kind==='artifacts.published' && current?.status!=='cancelled' && current?.status!=='stopping' && !next.bundles.some(b=>b.bundle_id===p.bundle_id))next.bundles.push(p);
  if(e.kind==='request.failed' || e.kind==='input.required') {next.runs[e.turn_id]={turnId:e.turn_id,taskId:e.task_id,attemptId:e.attempt_id,status:e.kind==='request.failed'?'failed':'needs_input',confirmed:null};next.notice=p.text;}
  return next;
}
