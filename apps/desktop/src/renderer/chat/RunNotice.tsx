import type { Run } from './public-events';
import Button from '../components/Button';
export default function RunNotice({run,onStop}:{run:Run;onStop:()=>void}) {
  if(!['pending','stopping','needs_input'].includes(run.status))return null;
  return <div className="run-notice" role="status"><p>{run.status==='stopping'?'正在停止…':run.status==='needs_input'?'等待补充资料。':'正在准备回答…'}</p><Button className="primary" onClick={onStop} disabled={run.status==='stopping'}>{run.status==='stopping'?'正在停止…':run.status==='needs_input'?'放弃此任务':'停止'}</Button></div>;
}
