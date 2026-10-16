import { useEffect, useRef, useState } from 'react';
import { getDocument, GlobalWorkerOptions, type PDFDocumentProxy } from 'pdfjs-dist';
import workerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url';
import InlineNotice from '../components/InlineNotice';
export default function PdfPreview({data}:{data:string}) {
  const canvas=useRef<HTMLCanvasElement>(null);const [document,setDocument]=useState<PDFDocumentProxy|null>(null);const [page,setPage]=useState(1);const [text,setText]=useState('');const [error,setError]=useState('');const [rendered,setRendered]=useState(false);
  useEffect(()=>{
    let active=true;const worker=new Worker(workerUrl,{type:'module'});GlobalWorkerOptions.workerPort=worker;
    const bytes=Uint8Array.from(atob(data),value=>value.charCodeAt(0));
    const task=getDocument({data:bytes,enableXfa:false,useWorkerFetch:false,disableAutoFetch:true,disableStream:true});
    task.promise.then(value=>{if(active)setDocument(value);}).catch(()=>{if(active)setError('PDF 预览暂不可用，可保存原文件后打开。');});
    return ()=>{active=false;void task.destroy();worker.terminate();GlobalWorkerOptions.workerPort=null;};
  },[data]);
  useEffect(()=>{
    if(!document)return;let active=true;let renderTask:ReturnType<Awaited<ReturnType<PDFDocumentProxy['getPage']>>['render']>|undefined;setRendered(false);setError('');
    void document.getPage(page).then(async pdfPage=>{
      if(!active||!canvas.current)return;const natural=pdfPage.getViewport({scale:1});const scale=Math.min(1.25,4096/Math.max(natural.width,natural.height));const viewport=pdfPage.getViewport({scale});const current=canvas.current;current.width=Math.ceil(viewport.width);current.height=Math.ceil(viewport.height);
      const context=current.getContext('2d');if(!context)throw new Error();
      renderTask=pdfPage.render({canvas:current,canvasContext:context,viewport});await renderTask.promise;
      const content=await pdfPage.getTextContent();if(active){setText(content.items.map(item=>'str' in item?item.str:'').join(' '));setRendered(true);}
    }).catch(error=>{if(active&&error?.name!=='RenderingCancelledException')setError('PDF 预览暂不可用，可保存原文件后打开。');});
    return ()=>{active=false;renderTask?.cancel();};
  },[document,page]);
  return <div className="pdf-preview">{error?<InlineNotice>{error}</InlineNotice>:<><div className="pdf-controls"><button disabled={!document||page===1} onClick={()=>setPage(value=>value-1)}>上一页</button><span>{document?`第 ${page} / ${document.numPages} 页`:'正在读取 PDF…'}</span><button disabled={!document||page===document.numPages} onClick={()=>setPage(value=>value+1)}>下一页</button></div><canvas ref={canvas} aria-label="PDF 页面预览" data-rendered={rendered} role="img"/><p className="sr-only pdf-page-text">{text}</p>{!rendered&&<p role="status">正在绘制页面…</p>}</>}</div>;
}
