import { useState } from 'react';
import Button from '../components/Button';
import InlineNotice from '../components/InlineNotice';
export default function Diagnostics({onError}:{onError:(error:unknown)=>void}) {
  const [busy,setBusy]=useState(false);const [notice,setNotice]=useState('');
  return <><h2>诊断</h2><p>保存本地脱敏诊断，用于核对版本、连接能力、错误代码和用量。</p><InlineNotice>默认不包含密钥、完整用户正文、内部提示或原始模型回答。文件由你选择位置，保存在本地。</InlineNotice><Button busy={busy} onClick={async()=>{setBusy(true);try{const result=await window.workbench.exportDiagnostics();setNotice(result.cancelled?'已取消保存。':'脱敏诊断已保存。');}catch(error){onError(error);}finally{setBusy(false);}}}>保存脱敏诊断</Button><p role="status">{notice}</p></>;
}
