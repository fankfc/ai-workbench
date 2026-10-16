import { useEffect, useRef, type ReactNode } from 'react';
export default function Modal({title,onClose,children,className=''}:{title:string;onClose:()=>void;children:ReactNode;className?:string}) {
  const ref=useRef<HTMLDivElement>(null);
  useEffect(()=>{const previous=document.activeElement as HTMLElement|null;ref.current?.querySelector<HTMLElement>('button,input,select,textarea,[tabindex="0"]')?.focus();return ()=>previous?.focus();},[]);
  return <div className="overlay" onMouseDown={event=>{if(event.target===event.currentTarget)onClose();}}><div ref={ref} role="dialog" aria-modal="true" aria-label={title} className={`dialog ${className}`} onKeyDown={event=>{
    if(event.key==='Escape'){event.stopPropagation();onClose();}
    if(event.key==='Tab'){const items=[...ref.current!.querySelectorAll<HTMLElement>('button:not(:disabled),input,select,textarea,[tabindex="0"]')];if(!items.length)return;const first=items[0],last=items[items.length-1];if(event.shiftKey&&document.activeElement===first){event.preventDefault();last.focus();}else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first.focus();}}
  }}><h2>{title}</h2>{children}</div></div>;
}
