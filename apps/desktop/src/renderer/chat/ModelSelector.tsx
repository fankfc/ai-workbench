import type { Connection } from '../../shared/desktop-bridge';
export function usable(connection:Connection,mode:'fake'|'real') {return connection.enabled&&connection.available&&connection.provider_mode===mode&&(mode==='fake'||connection.identity_status==='verified')&&['claude','gpt'].includes(connection.family);}
export default function ModelSelector({connections,value,onChange,mode}:{connections:Connection[];value:string;onChange:(value:string)=>void;mode:'fake'|'real'}) {
  const options=connections.filter(connection=>['claude','gpt'].includes(connection.family));
  return <select aria-label="指导模型 A" value={value} onChange={event=>onChange(event.target.value)}><option value="">选择模型</option>{options.map(connection=><option key={connection.id} value={connection.id} disabled={!usable(connection,mode)}>{connection.family==='claude'?'Claude':'GPT'}{connection.provider_mode==='fake'?' · 演示':!usable(connection,mode)?' · 未核验':''}</option>)}{!options.some(c=>c.family==='claude')&&<option disabled>Claude · 未配置</option>}{!options.some(c=>c.family==='gpt')&&<option disabled>GPT · 未配置</option>}</select>;
}
