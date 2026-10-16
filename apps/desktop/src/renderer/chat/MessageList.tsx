import { useEffect, useRef, useState } from 'react';
import type { PublicMessage } from '../../shared/desktop-bridge';
export function SafeText({text}:{text:string}) {
  return <>{text.split(/(```[\s\S]*?```)/g).map((part,index)=>part.startsWith('```')?<pre key={index} tabIndex={0} aria-label="代码块"><code>{part.slice(3,-3).replace(/^[^\n]*\n/,'')}</code></pre>:<div className="message-text" key={index}>{part}</div>)}</>;
}
export default function MessageList({messages,children}:{messages:PublicMessage[];children?:React.ReactNode}) {
  const scroller=useRef<HTMLDivElement>(null);const nearBottom=useRef(true);const [newAnswer,setNewAnswer]=useState(false);
  useEffect(()=>{if(nearBottom.current){scroller.current?.scrollTo({top:scroller.current.scrollHeight});setNewAnswer(false);}else setNewAnswer(true);},[messages.length]);
  return <div id="conversation" tabIndex={-1} ref={scroller} className="messages" onScroll={()=>{const el=scroller.current!;nearBottom.current=el.scrollHeight-el.scrollTop-el.clientHeight<80;}}><div className="messages-inner">{!messages.length&&<p className="empty">描述你要完成的任务，也可以添加文件。</p>}{messages.filter(message=>['message.accepted','answer.published','input.required','request.failed','request.cancelled'].includes(message.kind)).map(message=><article key={message.id} className={`message ${message.kind==='message.accepted'?'user':'assistant'}`} lang={message.language}><div className="message-role">{message.kind==='message.accepted'?'你':'回答'}{message.historical?' · 历史版本':''}</div><SafeText text={message.text}/><div className="message-footer"><button className="link" aria-label="复制消息" onClick={()=>navigator.clipboard.writeText(message.text)}>复制</button></div></article>)}{children}{newAnswer&&<button className="new-answer" onClick={()=>{scroller.current?.scrollTo({top:scroller.current.scrollHeight});nearBottom.current=true;setNewAnswer(false);}}>有新回答</button>}</div></div>;
}
