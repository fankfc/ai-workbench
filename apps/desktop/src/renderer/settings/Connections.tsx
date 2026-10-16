import { useState } from 'react';
import type { Settings } from '../../shared/desktop-bridge';
import Button from '../components/Button';
import InlineNotice from '../components/InlineNotice';
export default function Connections({settings,onRefresh,onError}:{settings:Settings;onRefresh:()=>void;onError:(error:unknown)=>void}) {
  const [checking,setChecking]=useState('');const [checked,setChecked]=useState<Record<string,string>>({});
  return <><h2>模型连接</h2><p>每轮发送使用已核验的连接。切换模型只影响下一轮。</p><InlineNotice>真实模型连接仍需要运行能力核验。填写模型名称不会建立连接。</InlineNotice>{settings.connections.map(connection=>{
    const verified=connection.identity_status==='verified'&&connection.available&&connection.provider_mode==='real';
    const name=connection.family==='claude'?'Claude':connection.family==='gpt'?'GPT':'ZCode / GLM';
    const status=checking===connection.id?'检测中…':!connection.enabled?'尚未配置':connection.provider_mode==='fake'?'演示 · 模拟连接':verified?'已核验':connection.identity_status==='unknown'?'身份尚未核验':'连接暂不可用';
    return <section className="settings-card" key={connection.id}><h3>{connection.role==='B'?'执行模型 B':'指导模型 A'} · {name}</h3><p className={`connection-state ${verified?'verified':''}`}>{status}</p><p className="muted">实际模型：{connection.model_id??'暂不可用'} · 配置版本：{connection.connection_version??'尚未建立'}</p><p>{connection.reason??(connection.provider_mode==='fake'?'模拟响应只用于演示和测试。':'连接能力由后端实际检测。')}</p><p className="muted">启动、取消、恢复和用量能力：{Object.keys(connection.capabilities).length?Object.entries(connection.capabilities).map(([key,value])=>`${key} ${value===true?'可用':'暂不可用'}`).join('；'):'尚未实际探测。'}</p>{checked[connection.id]&&<p className="muted">{checked[connection.id]}</p>}<Button busy={checking===connection.id} onClick={async()=>{setChecking(connection.id);try{const result=await window.workbench.probeConnection({connectionId:connection.id});setChecked(previous=>({...previous,[connection.id]:(result as any).generation_tested?'检测结果已更新。':'已检查运行注册状态；尚未实际调用模型。'}));onRefresh();}catch(error){onError(error);}finally{setChecking('');}}}>检测连接</Button></section>})}<p className="muted">凭据使用既有 CLI 登录或系统安全存储。当前界面不接收和显示密钥；真实登录配置入口尚未装配。</p></>;
}
