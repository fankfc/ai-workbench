import { resolve, relative, isAbsolute } from 'node:path';
export function localAssetPath(root:string,requestUrl:string):string {
  const url=new URL(requestUrl);
  if(url.protocol!=='workbench:'||url.hostname!=='desktop'||url.search||url.username||url.password)throw new Error('资源地址无效。');
  const path=decodeURIComponent(url.pathname);
  if(path.includes('\\')||path.includes('\0'))throw new Error('资源地址无效。');
  const target=resolve(root,'.'+path);const segment=relative(root,target);
  if(!segment||segment.startsWith('..')||isAbsolute(segment))throw new Error('资源地址无效。');
  return target;
}
