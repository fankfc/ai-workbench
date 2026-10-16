import { describe,it,expect } from 'vitest';
import { resolve } from 'node:path';
import { localAssetPath } from '../../apps/desktop/src/main/local-assets';
describe('packaged local resource origin',()=>{
 it('serves only fixed app assets',()=>{expect(localAssetPath(resolve('apps/desktop/dist/renderer'),'workbench://desktop/assets/worker.mjs')).toBe(resolve('apps/desktop/dist/renderer/assets/worker.mjs'));});
 it('rejects other hosts, encoded escapes and ambient filesystem paths',()=>{for(const url of ['workbench://other/index.html','file:///C:/secret','workbench://desktop/%2e%2e%2fsecret','workbench://desktop/assets%5csecret','workbench://desktop/index.html?path=C:/secret'])expect(()=>localAssetPath(resolve('apps/desktop/dist/renderer'),url)).toThrow();});
});
