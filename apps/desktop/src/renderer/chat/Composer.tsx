import { useRef } from 'react';
import type { Attachment, Connection, Preferences } from '../../shared/desktop-bridge';
import type { Draft } from './drafts';
import ModelSelector from './ModelSelector';
import Button from '../components/Button';
import TaskDetails from './TaskDetails';
export default function Composer({draft,onChange,onSend,onFiles,onRemove,connections,mode,preferences,disabled,sending}:{draft:Draft;onChange:(draft:Draft)=>void;onSend:()=>void;onFiles:()=>void;onRemove:(attachment:Attachment)=>void;connections:Connection[];mode:'fake'|'real';preferences:Preferences;disabled:boolean;sending:boolean}) {
  const composing=useRef(false);
  return <div className="composer-wrap"><div className="composer"><div className="attachments">{draft.attachments.map(file=><div key={file.id} className="attachment"><span className="attachment-name">{file.name}</span><span>{file.status==='ready'?'可用':file.status==='reading'?'读取中':'失败'}</span><button aria-label={`移除 ${file.name}`} onClick={()=>onRemove(file)}>×</button></div>)}</div><textarea id="composer" aria-label="消息输入" placeholder="提问或描述任务…" value={draft.text} onChange={event=>onChange({...draft,text:event.target.value,requestId:null})} onCompositionStart={()=>{composing.current=true;}} onCompositionEnd={()=>{composing.current=false;}} onKeyDown={event=>{
    if(event.key!=='Enter'||composing.current||event.nativeEvent.isComposing||event.nativeEvent.keyCode===229)return;
    const shouldSend=preferences.send_shortcut==='enter'?!event.shiftKey:!!event.ctrlKey&&!event.shiftKey;
    if(shouldSend){event.preventDefault();if(!disabled&&!sending)onSend();}
  }}/><TaskDetails draft={draft} onChange={onChange}/><div className="composer-actions"><div className="composer-options"><Button onClick={onFiles} disabled={sending}>添加文件</Button><ModelSelector connections={connections} value={draft.connectionId} onChange={connectionId=>onChange({...draft,connectionId,requestId:null})} mode={mode}/><select aria-label="任务类型" value={draft.domain} onChange={event=>onChange({...draft,domain:event.target.value,requestId:null})}><option value="mixed">综合任务</option><option value="code">编程</option><option value="paper">论文</option><option value="document">普通文档</option></select></div><Button className="primary" onClick={onSend} disabled={disabled} busy={sending}>发送</Button></div></div><p className="composer-hint">{preferences.send_shortcut==='enter'?'Enter 发送，Shift + Enter 换行。':'Ctrl + Enter 发送，Enter 换行。'} 中文输入法选字时不会发送。</p></div>;
}
