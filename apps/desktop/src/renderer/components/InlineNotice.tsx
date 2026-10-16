import type { ReactNode } from 'react';
export default function InlineNotice({children,error=false,action}:{children:ReactNode;error?:boolean;action?:ReactNode}) {return <div className={`notice ${error?'error':''}`} role={error?'alert':'status'}>{error&&<span aria-hidden="true">！ </span>}{children}{action&&<div className="notice-actions">{action}</div>}</div>;}
