import type { Artifact, Bundle } from '../../shared/desktop-bridge';
import Button from '../components/Button';
export default function ArtifactCard({artifact,bundle,onPreview,onSave}:{artifact:Artifact;bundle:Bundle;onPreview:(artifact:Artifact)=>void;onSave:(artifacts:Artifact[])=>void}) {
  return <section className="artifact-card"><h3>{artifact.file_name}</h3><p className="muted">{artifact.format.toUpperCase()} · {bundle.version_id}{bundle.historical?' · 历史版本':''} · {artifact.size_bytes.toLocaleString()} 字节</p><div className="artifact-row-actions"><Button onClick={()=>onPreview(artifact)}>预览</Button><Button onClick={()=>onSave([artifact])}>保存</Button></div></section>;
}
