import { describe, expect, it, vi } from 'vitest';
import { mkdtemp, readFile, writeFile, readdir } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { createHash } from 'node:crypto';
import { link,unlink } from 'node:fs/promises';
vi.mock('electron',()=>({dialog:{}}));
import { safeFilename, verifyBytes, saveFilesAtomically } from '../../apps/desktop/src/main/artifact-files';
describe('artifact save safety',()=>{
  it('refuses paths, device names and corrupt bytes',()=>{for(const name of ['../private','C:\\secret','CON.md','report.md.'])expect(()=>safeFilename(name)).toThrow();expect(()=>verifyBytes(new Uint8Array([1]),'0'.repeat(64))).toThrow();});
  it('saves exact bytes and refuses an existing destination',async()=>{const root=await mkdtemp(join(tmpdir(),'artifact-unit-'));const bytes=new TextEncoder().encode('approved');const path=join(root,'report.md');expect(await saveFilesAtomically([{path,bytes}])).toEqual(['report.md']);expect(createHash('sha256').update(await readFile(path)).digest('hex')).toBe(createHash('sha256').update(bytes).digest('hex'));await expect(saveFilesAtomically([{path,bytes:new Uint8Array([2])}])).rejects.toThrow('同名');expect(await readFile(path,'utf8')).toBe('approved');});
  it('does not save the first member when the second path cannot be written',async()=>{const root=await mkdtemp(join(tmpdir(),'artifact-pair-unit-'));const bytes=new Uint8Array([1]);await expect(saveFilesAtomically([{path:join(root,'en.md'),bytes},{path:join(root,'missing','zh.md'),bytes}])).rejects.toThrow();expect(await readdir(root)).toEqual([]);});
  it('reports the remaining saved filename when rollback is refused by the filesystem',async()=>{const root=await mkdtemp(join(tmpdir(),'artifact-rollback-'));const first=join(root,'en.md');const second=join(root,'zh.md');const operations={link:async(source:string,target:string)=>{if(target===second)throw new Error('second member is unavailable');await link(source,target);},unlink:async(path:string)=>{if(path===first)throw new Error('file is held open');await unlink(path);}};try{await expect((saveFilesAtomically as any)([{path:first,bytes:new Uint8Array([1])},{path:second,bytes:new Uint8Array([1])}],operations)).rejects.toThrow('仍已保存：en.md');expect(await readdir(root)).toEqual(['en.md']);}finally{await unlink(first).catch(()=>{});}});
});
