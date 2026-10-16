import type { Artifact, Bundle } from '../../shared/desktop-bridge';
import Button from '../components/Button';
export default function ArtifactPair({artifacts,bundle,onPreview,onSave}:{artifacts:Artifact[];bundle:Bundle;onPreview:(artifact:Artifact)=>void;onSave:(artifacts:Artifact[])=>void}) {
  const english=artifacts.find(artifact=>artifact.language==='en');const chinese=artifacts.find(artifact=>artifact.language==='zh-CN');
  const valid=artifacts.length===2&&english&&chinese&&english.format===chinese.format&&english.artifact_pair_id===chinese.artifact_pair_id;
  return <section className="artifact-card"><h3>{english?.file_name??artifacts[0].file_name}</h3><p className="muted">{artifacts[0].format.toUpperCase()} · {bundle.version_id}{bundle.historical?' · 历史版本':''}</p>{artifacts.map(artifact=><div className="artifact-row" key={artifact.artifact_id}><span>{artifact.language==='en'?'英文原文':'中文译文'} · {artifact.file_name}</span><div className="artifact-row-actions"><Button onClick={()=>onPreview(artifact)}>预览{artifact.language==='en'?'英文':'中文'}</Button><Button onClick={()=>onSave([artifact])}>保存{artifact.language==='en'?'英文':'中文'}</Button></div></div>)}{valid?<Button onClick={()=>onSave(artifacts)} style={{marginTop:'var(--space-3)'}}>保存两份</Button>:<p role="alert">双语文件组不完整，暂不可作为完整交付保存。</p>}</section>;
}
