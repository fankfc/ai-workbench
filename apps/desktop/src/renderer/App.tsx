import { useEffect, useRef, useState } from 'react';
import type { Artifact, BackendStatus, Bundle, Conversation, Settings } from '../shared/desktop-bridge';
import Button from './components/Button';
import InlineNotice from './components/InlineNotice';
import Modal from './components/Modal';
import Composer from './chat/Composer';
import MessageList from './chat/MessageList';
import RunNotice from './chat/RunNotice';
import ArtifactCard from './chat/ArtifactCard';
import ArtifactPair from './chat/ArtifactPair';
import { usable } from './chat/ModelSelector';
import { loadDraft, saveDraft, type Draft } from './chat/drafts';
import { emptyPublicState, reducePublic, acceptReceipt, type PublicState, type Run } from './chat/public-events';
import { profileInputs } from './chat/profile-inputs';
import Connections from './settings/Connections';
import Preferences from './settings/Preferences';
import Usage from './settings/Usage';
import Storage from './settings/Storage';
import Diagnostics from './settings/Diagnostics';
import DocumentPreview from './documents/DocumentPreview';

const defaults:Settings={version:1,preferences:{theme:'system',font_size:16,send_shortcut:'enter',close_behavior:'quit'},connections:[]};
export function friendlyError(error:unknown):string {
  const message=error instanceof Error?error.message:String(error);
  const clean=message.split('Error:').pop()?.trim();
  return clean&&/[\u4e00-\u9fff]/.test(clean)&&clean.length<400?clean:'操作暂未完成，请重试。';
}
function currentRoute(){const value=location.hash.slice(1);return /^\/chat\/[a-zA-Z0-9_-]+$/.test(value)||['/settings/connections','/settings/preferences','/settings/storage','/settings/diagnostics','/usage'].includes(value)?value:'/chat/new';}
export default function App() {
  const [route,setRoute]=useState(currentRoute);const routeConversation=route.startsWith('/chat/')&&route!=='/chat/new'?route.split('/')[2]:'';
  const routeRef=useRef(route);routeRef.current=route;const navigationVersion=useRef(0);
  const [settings,setSettings]=useState<Settings>(defaults);const [backend,setBackend]=useState<BackendStatus>({state:'starting',provider_mode:'real',message:'正在连接本地服务…'});
  const [conversations,setConversations]=useState<Conversation[]>([]);const [nextOffset,setNextOffset]=useState<number|null>(null);const [query,setQuery]=useState('');const [archived,setArchived]=useState(false);
  const [draft,setDraft]=useState<Draft>(()=>loadDraft(routeConversation||'new'));const draftRef=useRef(draft);const draftKey=useRef(routeConversation||'new');
  const [publicState,setPublicState]=useState<PublicState>(emptyPublicState);const [bundles,setBundles]=useState<Bundle[]>([]);const [error,setError]=useState('');const [notice,setNotice]=useState('');const [sending,setSending]=useState(false);const submitting=useRef(new Map<string,symbol>());const cancelling=useRef(new Set<string>());
  const [drawer,setDrawer]=useState(false);const [collapsed,setCollapsed]=useState(false);const menuButton=useRef<HTMLButtonElement>(null);const [actionConversation,setActionConversation]=useState('');
  const [dialog,setDialog]=useState<{kind:'rename'|'delete';conversation:Conversation}|null>(null);const [title,setTitle]=useState('');
  const [preview,setPreview]=useState<{artifact:Artifact;bundle:Bundle}|null>(null);
  const showError=(value:unknown)=>setError(friendlyError(value));
  const navigate=(path:string)=>{navigationVersion.current++;routeRef.current=path;location.hash=path;setRoute(path);setDrawer(false);setError('');setNotice('');setPreview(null);};
  const ownsPage=(conversation:string,version:number)=>routeRef.current==='/chat/'+conversation&&navigationVersion.current===version;
  const changeDraft=(value:Draft)=>{draftRef.current=value;setDraft(value);saveDraft(draftKey.current,value);};
  const refreshConversations=async(offset=0)=>{try{const page=await window.workbench.listConversations({query,archived,offset});setConversations(previous=>offset?[...previous,...page.items]:page.items);setNextOffset(page.next_offset);}catch(error){showError(error);}};
  const refreshSettings=async()=>{try{setSettings(await window.workbench.getSettings());}catch(error){showError(error);}};
  useEffect(()=>{const onHash=()=>{const next=currentRoute();if(routeRef.current!==next)navigationVersion.current++;routeRef.current=next;setRoute(next);};window.addEventListener('hashchange',onHash);return ()=>window.removeEventListener('hashchange',onHash);},[]);
  useEffect(()=>{document.documentElement.dataset.theme=settings.preferences.theme;document.documentElement.style.setProperty('--font-size',`${settings.preferences.font_size}px`);},[settings.preferences]);
  useEffect(()=>{
    let active=true;const check=async()=>{try{const status=await window.workbench.status();if(active)setBackend(status);}catch{if(active)setBackend({state:'offline',provider_mode:'real',message:'桌面服务暂不可用。草稿已保存。'});}};
    void check();const timer=setInterval(check,500);return ()=>{active=false;clearInterval(timer);};
  },[]);
  useEffect(()=>{if(backend.state==='ready'){void refreshSettings();void refreshConversations();}},[backend.state]);
  useEffect(()=>{if(backend.state==='ready'){const timer=setTimeout(()=>{void refreshConversations();},150);return ()=>clearTimeout(timer);}},[query,archived]);
  useEffect(()=>{
    const key=routeConversation||'new';draftKey.current=key;const saved=loadDraft(key);draftRef.current=saved;setDraft(saved);setPublicState(emptyPublicState());setBundles([]);setSending(submitting.current.has(key));
  },[routeConversation]);
  useEffect(()=>{
    if(!routeConversation||backend.state!=='ready')return;
    let active=true;let unsubscribe:(()=>void)|undefined;
    Promise.all([window.workbench.listMessages({conversationId:routeConversation}),window.workbench.listArtifacts({conversationId:routeConversation}).catch(()=>({items:[]}))]).then(([history,files])=>{
      if(!active)return;setPublicState(previous=>({...previous,messages:[...history.items,...previous.messages.filter(message=>!history.items.some(value=>value.id===message.id))]}));setBundles(files.items);
      unsubscribe=window.workbench.subscribePublic({conversationId:routeConversation,afterSeq:0},frame=>{
        if(!active)return;
        setPublicState(previous=>reducePublic(previous,frame,routeConversation));
      });
    }).catch(error=>{if(active)showError(error);});
    return ()=>{active=false;unsubscribe?.();};
  },[routeConversation,backend.state]);
  useEffect(()=>{
    if(!draftRef.current.connectionId&&settings.connections.length){const selected=settings.connections.find(connection=>connection.family==='claude'&&usable(connection,backend.provider_mode))??settings.connections.find(connection=>usable(connection,backend.provider_mode));if(selected)changeDraft({...draftRef.current,connectionId:selected.id});}
  },[settings.connections,routeConversation]);
  useEffect(()=>{const keydown=(event:KeyboardEvent)=>{if(event.ctrlKey&&event.key.toLowerCase()==='n'){event.preventDefault();navigate('/chat/new');setTimeout(()=>document.getElementById('composer')?.focus(),0);}if(event.ctrlKey&&event.key.toLowerCase()==='k'){event.preventDefault();setDrawer(true);setTimeout(()=>document.getElementById('search-conversations')?.focus(),0);}if(event.key==='Escape'&&drawer){setDrawer(false);menuButton.current?.focus();}};window.addEventListener('keydown',keydown);return ()=>window.removeEventListener('keydown',keydown);},[drawer]);
  const getConversation=async(snapshot=draftRef.current)=>{
    if(routeConversation)return routeConversation;
    const origin=routeRef.current;const version=navigationVersion.current;
    const created=await window.workbench.createConversation({title:snapshot.text.trim().slice(0,40)||'新会话'});saveDraft(created.id,snapshot);if(routeRef.current===origin&&navigationVersion.current===version){draftKey.current=created.id;navigate('/chat/'+created.id);}void refreshConversations();return created.id;
  };
  const selectedConnection=settings.connections.find(connection=>connection.id===draft.connectionId);
  const activeRun=Object.values(publicState.runs).find(run=>['pending','stopping'].includes(run.status));
  const sendDisabled=backend.state!=='ready'||!draft.text.trim()||!selectedConnection||!usable(selectedConnection,backend.provider_mode)||draft.attachments.some(file=>file.status!=='ready')||!!activeRun;
  const send=async()=>{
    const origin=draftKey.current;if(submitting.current.has(origin)||sendDisabled||!selectedConnection?.connection_version)return;
    const operation=Symbol();submitting.current.set(origin,operation);setSending(true);setError('');let conversationId='';let version=navigationVersion.current;
    try {
      const submitted={...draftRef.current,requestId:draftRef.current.requestId??crypto.randomUUID(),submittedText:draftRef.current.text};changeDraft(submitted);
      const inputs=profileInputs(submitted);conversationId=await getConversation(submitted);version=navigationVersion.current;saveDraft(conversationId,submitted);submitting.current.set(conversationId,operation);if(origin!==conversationId&&submitting.current.get(origin)===operation)submitting.current.delete(origin);
      const accepted=await window.workbench.submitTurn({conversationId,text:submitted.text,provider_profile_id:submitted.connectionId,client_request_id:submitted.requestId!,connection_version:selectedConnection.connection_version,attachment_ids:submitted.attachments.map(file=>file.id),domain:submitted.domain,...(inputs!==undefined?{profile_inputs:inputs}:{})});
      const stored=loadDraft(conversationId);if(stored.requestId===submitted.requestId){const cleared={...stored,text:'',attachments:[],requestId:null,submittedText:undefined};saveDraft(conversationId,cleared);if(ownsPage(conversationId,version))changeDraft(cleared);}
      if(ownsPage(conversationId,version))setPublicState(previous=>acceptReceipt(previous,accepted));
      await refreshConversations();
    }catch(error){if(conversationId?ownsPage(conversationId,version):draftKey.current===origin&&navigationVersion.current===version)showError(error);}finally{for(const key of [origin,conversationId])if(submitting.current.get(key)===operation)submitting.current.delete(key);setSending(submitting.current.has(draftKey.current));}
  };
  const stop=async(run:Run)=>{
    const conversationId=routeConversation;const version=navigationVersion.current;
    if(cancelling.current.has(run.taskId))return;cancelling.current.add(run.taskId);
    setPublicState(previous=>({...previous,runs:{...previous.runs,[run.turnId]:{...run,status:'stopping'}},notice:'正在停止…'}));
    try{const status=await window.workbench.cancelTurn({taskId:run.taskId});if(!ownsPage(conversationId,version))return;setPublicState(previous=>{const current=previous.runs[run.turnId];if(current&&['completed','failed'].includes(current.status))return previous;return {...previous,runs:{...previous.runs,[run.turnId]:{...current??run,status:status.cancel_requested?'cancelled':'stopping',confirmed:status.external_stop_confirmed}},notice:status.external_stop_confirmed===true?'已停止，已保存当前进度。':status.cancel_pending_remote?'取消请求已记录，正在等待外部停止确认。':'取消请求已记录，已保存当前进度。'};});document.getElementById('composer')?.focus();}catch(error){if(ownsPage(conversationId,version)){showError(error);setPublicState(previous=>{const current=previous.runs[run.turnId];return current?.status==='stopping'?{...previous,runs:{...previous.runs,[run.turnId]:{...current,status:run.status}}}:previous;});}cancelling.current.delete(run.taskId);}
  };
  const addFiles=async()=>{const source={...draftRef.current};let conversationId='';let version=navigationVersion.current;try{conversationId=await getConversation(source);version=navigationVersion.current;const files=await window.workbench.chooseFiles({conversationId});const stored=loadDraft(conversationId);const next={...stored,attachments:[...stored.attachments,...files],requestId:null};saveDraft(conversationId,next);if(ownsPage(conversationId,version))changeDraft(next);}catch(error){if(conversationId&&ownsPage(conversationId,version))showError(error);}};
  const removeFile=async(attachment:any)=>{const conversationId=routeConversation;const version=navigationVersion.current;try{if(conversationId)await window.workbench.removeAttachment({conversationId,attachmentId:attachment.id});const stored=loadDraft(conversationId||'new');const next={...stored,attachments:stored.attachments.filter(file=>file.id!==attachment.id),requestId:null};saveDraft(conversationId||'new',next);if(ownsPage(conversationId,version))changeDraft(next);}catch(error){if(ownsPage(conversationId,version))showError(error);}};
  const save=async(bundle:Bundle,artifacts:Artifact[])=>{const conversationId=routeConversation;const version=navigationVersion.current;try{const input={conversationId,bundleId:bundle.bundle_id,artifactIds:artifacts.map(artifact=>artifact.artifact_id)};const result=await(artifacts.length===2?window.workbench.saveArtifactPair(input):window.workbench.saveArtifact(input));if(ownsPage(conversationId,version))setNotice(result.cancelled?'已取消保存。':`已保存：${result.saved.join('、')}`);}catch(error){if(ownsPage(conversationId,version))showError(error);}};
  const current=conversations.find(conversation=>conversation.id===routeConversation);
  const allBundles=[...bundles,...publicState.bundles.filter(bundle=>!bundles.some(value=>value.bundle_id===bundle.bundle_id))];
  const settingsPage=route.startsWith('/settings/');const titleText=route==='/usage'?'用量':settingsPage?'设置':current?.title??'新会话';
  return <div className={`${drawer?'drawer-open':''} ${collapsed?'collapsed':''}`} style={{height:'100%'}}><a className="skip" href="#conversation" onClick={event=>{event.preventDefault();document.getElementById('conversation')?.focus();}}>跳到对话</a><a className="skip skip-input" href="#composer" onClick={event=>{event.preventDefault();document.getElementById('composer')?.focus();}}>跳到输入框</a><div className="app-shell"><button className="drawer-backdrop" aria-label="关闭导航" onClick={()=>{setDrawer(false);menuButton.current?.focus();}}/><aside className="sidebar" aria-label="会话导航"><div className="brand">协作工作台</div><Button className="new-chat" onClick={()=>navigate('/chat/new')} aria-label="新建会话">＋ 新建会话</Button><input id="search-conversations" aria-label="搜索会话" placeholder="搜索会话" value={query} onChange={event=>setQuery(event.target.value)}/><ul className="conversation-list">{conversations.map(conversation=><li key={conversation.id}><div className="conversation-row"><button className="conversation-title" aria-current={conversation.id===routeConversation?'page':undefined} onClick={()=>navigate('/chat/'+conversation.id)}>{conversation.pinned?'● ':''}{conversation.title}</button><button className="conversation-menu" aria-label={`管理 ${conversation.title}`} onClick={()=>setActionConversation(actionConversation===conversation.id?'':conversation.id)}>···</button></div>{actionConversation===conversation.id&&<div className="conversation-actions"><Button onClick={()=>{setDialog({kind:'rename',conversation});setTitle(conversation.title);}}>重命名</Button><Button onClick={async()=>{try{await window.workbench.updateConversation({conversationId:conversation.id,pinned:!conversation.pinned,expected_version:conversation.version});await refreshConversations();}catch(error){showError(error);}}}>{conversation.pinned?'取消置顶':'置顶'}</Button><Button onClick={async()=>{try{await window.workbench.updateConversation({conversationId:conversation.id,archived:!conversation.archived,expected_version:conversation.version});setNotice(conversation.archived?'已恢复会话。':'已归档，可在归档会话中恢复。');await refreshConversations();}catch(error){showError(error);}}}>{conversation.archived?'恢复':'归档'}</Button><Button onClick={()=>setDialog({kind:'delete',conversation})}>删除</Button></div>}</li>)}{!conversations.length&&<li className="muted">{query?'没有匹配的会话。':'暂无会话。'}</li>}{nextOffset!==null&&<li><Button onClick={()=>refreshConversations(nextOffset)}>加载更多</Button></li>}</ul><Button className="archive-toggle" onClick={()=>setArchived(!archived)}>{archived?'返回会话':'归档会话'}</Button><nav className="nav-links"><Button onClick={()=>navigate('/settings/connections')}>设置</Button><Button onClick={()=>navigate('/usage')}>用量</Button><Button aria-label="折叠导航" onClick={()=>setCollapsed(!collapsed)}>收起</Button></nav></aside><main className="main"><header className="topbar"><div style={{display:'flex',gap:'var(--space-2)',alignItems:'center',minWidth:0}}><button ref={menuButton} className="menu-toggle" aria-label="打开导航" aria-expanded={drawer} onClick={()=>{setCollapsed(false);setDrawer(!drawer);}}>☰</button><h1>{titleText}</h1></div><div className="topbar-right">{backend.provider_mode==='fake'&&<span className="demo-badge">演示模式</span>}{!settingsPage&&route!=='/usage'&&<span className="muted">{selectedConnection?.family==='claude'?'Claude':selectedConnection?.family==='gpt'?'GPT':'未连接'}</span>}</div></header>{route.startsWith('/chat/')?<div className="chat-page"><MessageList messages={publicState.messages}><>{backend.state!=='ready'&&<InlineNotice error={backend.state==='offline'} action={backend.state==='offline'?<Button onClick={()=>window.workbench.retryBackend().then(setBackend).catch(showError)}>重试连接</Button>:undefined}>{backend.message}</InlineNotice>}{backend.state==='ready'&&!settings.connections.some(connection=>usable(connection,backend.provider_mode))&&<InlineNotice action={<Button onClick={()=>navigate('/settings/connections')}>打开设置</Button>}>先完成模型连接，即可开始。草稿会保留。</InlineNotice>}{error&&<InlineNotice error>{error}</InlineNotice>}{notice&&<InlineNotice>{notice}</InlineNotice>}{publicState.notice&&<p role="status" aria-live="polite">{publicState.notice}</p>}{Object.values(publicState.runs).map(run=><RunNotice key={run.turnId} run={run} onStop={()=>stop(run)}/>)}{allBundles.map(bundle=>{const grouped=new Set<string>();return <div key={bundle.bundle_id}>{bundle.artifacts.map((artifact:Artifact)=>{if(artifact.artifact_pair_id){if(grouped.has(artifact.artifact_pair_id))return null;grouped.add(artifact.artifact_pair_id);return <ArtifactPair key={artifact.artifact_pair_id} artifacts={bundle.artifacts.filter((value:Artifact)=>value.artifact_pair_id===artifact.artifact_pair_id)} bundle={bundle} onPreview={artifact=>setPreview({artifact,bundle})} onSave={artifacts=>save(bundle,artifacts)}/>;}return <ArtifactCard key={artifact.artifact_id} artifact={artifact} bundle={bundle} onPreview={artifact=>setPreview({artifact,bundle})} onSave={artifacts=>save(bundle,artifacts)}/>;})}</div>})}</></MessageList><Composer draft={draft} onChange={changeDraft} onSend={send} onFiles={addFiles} onRemove={removeFile} connections={settings.connections} mode={backend.provider_mode} preferences={settings.preferences} disabled={sendDisabled} sending={sending}/></div>:<div className="page"><div className="page-inner">{error&&<InlineNotice error>{error}</InlineNotice>}{settingsPage&&<nav className="settings-tabs">{[['connections','连接'],['preferences','偏好'],['storage','存储'],['diagnostics','诊断']].map(([path,label])=><Button key={path} aria-current={route===`/settings/${path}`?'page':undefined} onClick={()=>navigate(`/settings/${path}`)}>{label}</Button>)}</nav>}{route==='/settings/connections'&&<Connections settings={settings} onRefresh={refreshSettings} onError={showError}/>} {route==='/settings/preferences'&&<Preferences settings={settings} onSettings={setSettings} onError={showError}/>} {route==='/settings/storage'&&<Storage onError={showError}/>} {route==='/settings/diagnostics'&&<Diagnostics onError={showError}/>} {route==='/usage'&&<Usage onError={showError}/>}</div></div>}</main></div>{dialog&&<Modal title={dialog.kind==='rename'?'重命名会话':'删除会话'} onClose={()=>setDialog(null)}>{dialog.kind==='rename'?<input autoFocus aria-label="会话标题" value={title} maxLength={200} onChange={event=>setTitle(event.target.value)}/>:<p>删除“{dialog.conversation.title}”将先停止相关活动任务，并删除会话引用。此操作无法撤销。</p>}<div className="dialog-actions"><Button onClick={()=>setDialog(null)}>取消</Button><Button className="primary" onClick={async()=>{try{if(dialog.kind==='rename')await window.workbench.updateConversation({conversationId:dialog.conversation.id,title,expected_version:dialog.conversation.version});else{await window.workbench.deleteConversation({conversationId:dialog.conversation.id});if(routeConversation===dialog.conversation.id)navigate('/chat/new');}setDialog(null);await refreshConversations();}catch(error){showError(error);}}}>{dialog.kind==='rename'?'保存名称':'确认删除'}</Button></div></Modal>}{preview&&<DocumentPreview artifact={preview.artifact} input={{conversationId:routeConversation,bundleId:preview.bundle.bundle_id,artifactIds:[preview.artifact.artifact_id]}} onClose={()=>setPreview(null)}/>}</div>;
}
