import { useEffect, useState } from 'react';
import type { Artifact, ArtifactRequest, PreviewResult } from '../../shared/desktop-bridge';
import Modal from '../components/Modal';
import InlineNotice from '../components/InlineNotice';
import { SafeText } from '../chat/MessageList';
import PdfPreview from './PdfPreview';
export default function DocumentPreview({artifact,input,onClose}:{artifact:Artifact;input:ArtifactRequest;onClose:()=>void}) {
  const [preview,setPreview]=useState<PreviewResult|null>(null);
  useEffect(()=>{let active=true;window.workbench.previewArtifact(input).then(result=>{if(active)setPreview(result);}).catch(()=>{if(active)setPreview({available:false,format:artifact.format,language:artifact.language,message:'暂时无法预览，可保存后打开。'});});return ()=>{active=false;};},[]);
  return <Modal title={artifact.file_name} onClose={onClose} className="preview"><button onClick={onClose}>关闭预览</button><p className="muted">{artifact.language==='en'?'英文原文':'中文译文'}{artifact.format==='docx'?' · DOCX 派生预览，保存的是原文件。':''}</p><div className="preview-content" lang={artifact.language==='en'?'en':'zh-CN'}>{!preview?<p>正在读取预览…</p>:!preview.available?<InlineNotice>{preview.message}</InlineNotice>:preview.format==='pdf'?<PdfPreview data={preview.data??''}/>:<SafeText text={preview.text??''}/>}</div></Modal>;
}
