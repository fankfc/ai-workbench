import { describe, expect, it, vi } from 'vitest';
import { acceptHandshake } from '../../apps/desktop/src/shared/validation';
import { BackendSupervisor, childEnvironment } from '../../apps/desktop/src/main/backend';
import { spawn } from 'node:child_process';
import { mkdtemp,mkdir,readFile,rmdir } from 'node:fs/promises';
import * as filesystem from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { resolve, join } from 'node:path';
vi.mock('node:fs/promises',{spy:true});
describe('startup identity fence', () => {
  const ready = { kind:'backend.ready', port:12345, pid:123, instance_id:'expected', protocol_version:'1.0' };
  it('does not accept old occupied port or wrong process identity', () => {
    expect(acceptHandshake({...ready,instance_id:'old-process'},'expected',123)).toBe(false);
    expect(acceptHandshake({...ready,pid:456},'expected',123)).toBe(false);
  });
  it('does not accept unready, invalid port or a different protocol', () => {
    expect(acceptHandshake({...ready,kind:'backend.starting'},'expected',123)).toBe(false);
    expect(acceptHandshake({...ready,port:0},'expected',123)).toBe(false);
    expect(acceptHandshake({...ready,protocol_version:'2.0'},'expected',123)).toBe(false);
  });
});
describe('managed process lifecycle', () => {
  async function supervisor(mode:string) {
    const root=resolve('.');const dataRoot=await mkdtemp(join(tmpdir(),'desktop-unit-'));
    return new BackendSupervisor({root,dataRoot,providerMode:'fake',timeoutMs:300,spawnProcess:((_file:any,_args:any,options:any)=>spawn(process.execPath,[resolve('tests/desktop/support/backend-child.cjs')],{...options,env:{...options.env,TEST_BEHAVIOR:mode}})) as typeof spawn});
  }
  for(const [mode,message] of [['health-timeout','无法连接'],['early-exit','就绪前退出'],['old-port','启动超时']])it(`does not claim readiness for ${mode}`,async()=>{
    const backend=await supervisor(mode);await expect(backend.start()).rejects.toThrow(message);expect(backend.status.state).toBe('offline');
  });
  it('authenticates a healthy owned process and checkpoints shutdown',async()=>{const backend=await supervisor('normal');expect((await backend.start()).state).toBe('ready');expect((await backend.start()).state).toBe('ready');await backend.stop();expect(backend.status.state).toBe('offline');});
  it('does not spawn after shutdown cancels startup while the data directory is pending',async()=>{
    const backend=await supervisor('normal');const options=(backend as any).options;const originalSpawn=options.spawnProcess;let starts=0;options.spawnProcess=(...args:any[])=>{starts++;return originalSpawn(...args);};
    let release!:()=>void;let entered!:()=>void;const directoryEntered=new Promise<void>(resolve=>{entered=resolve;});const directoryReady=new Promise<void>(resolve=>{release=resolve;});
    const actualMkdir=(await vi.importActual<typeof filesystem>('node:fs/promises')).mkdir;
    const paused=vi.mocked(filesystem.mkdir).mockImplementationOnce(async(...args:Parameters<typeof filesystem.mkdir>)=>{entered();await directoryReady;return actualMkdir(...args);});
    const starting=backend.start().then(value=>({value}),error=>({error}));
    try {
      await directoryEntered;await backend.stop();expect(backend.status.state).toBe('offline');
      release();await starting;
      expect(starts).toBe(0);expect(backend.status.state).toBe('offline');
    } finally {release();paused.mockRestore();await starting;await backend.stop();}
  });
  it('rejects a new launch until stop finishes after an old launch has failed',async()=>{
    const backend=await supervisor('normal');const options=(backend as any).options;const originalSpawn=options.spawnProcess;options.timeoutMs=5000;
    let spawned!:()=>void;const childStarted=new Promise<void>(resolve=>{spawned=resolve;});let starts=0;
    options.spawnProcess=(...args:any[])=>{starts++;const child=starts===1?spawn(process.execPath,['-e','setInterval(()=>{},1000)'],args[2]):originalSpawn(...args);spawned();return child;};
    let release!:()=>void;let entered!:()=>void;const journalEntered=new Promise<void>(resolve=>{entered=resolve;});const journalReady=new Promise<void>(resolve=>{release=resolve;});
    const actualWrite=(await vi.importActual<typeof filesystem>('node:fs/promises')).writeFile;let writes=0;
    const paused=vi.mocked(filesystem.writeFile).mockImplementation(async(...args:Parameters<typeof filesystem.writeFile>)=>{if(String(args[0]).endsWith('desktop-recovery.json')&&++writes===2){entered();await journalReady;}return actualWrite(...args);});
    const first=backend.start().then(value=>({value}),error=>({error}));let stopping:Promise<void>|undefined;
    try {
      await childStarted;stopping=backend.stop();await journalEntered;await first;
      await expect(backend.start()).rejects.toThrow('正在退出');expect(starts).toBe(1);
      release();await stopping;expect((await backend.start()).state).toBe('ready');expect(starts).toBe(2);
    } finally {release();paused.mockRestore();await first;await stopping?.catch(()=>{});await backend.stop();}
  });
  it('shares one cleanup for concurrent stop callers',async()=>{
    const backend=await supervisor('normal');const options=(backend as any).options;let checkpoints=0;
    options.fetchRequest=(...args:Parameters<typeof fetch>)=>{if(String(args[0]).endsWith('/v1/checkpoint'))checkpoints++;return fetch(...args);};
    await backend.start();vi.mocked(filesystem.writeFile).mockClear();
    try {
      const first=backend.stop();const second=backend.stop();await Promise.all([first,second]);
      expect(checkpoints).toBe(1);
      expect(vi.mocked(filesystem.writeFile).mock.calls.filter(args=>String(args[0]).endsWith('desktop-recovery.json'))).toHaveLength(2);
      expect((backend as any).child).toBeUndefined();expect((await backend.start()).state).toBe('ready');
    } finally {await backend.stop();}
  });
  it('terminates the owned process even when the recovery journal cannot be written',async()=>{
    const backend=await supervisor('normal');await backend.start();const child=(backend as any).child;
    const journal=join((backend as any).options.dataRoot,'desktop-recovery.json');await mkdir(journal);
    try {
      await backend.stop();
      expect(child.exitCode!==null||child.signalCode!==null).toBe(true);
      expect(backend.status.state).toBe('offline');
      expect(backend.status.message).toContain('恢复记录尚未保存');
      expect(await backend.start()).toHaveProperty('state','ready');
    } finally {await rmdir(journal);await backend.stop();}
  });
  it('a late exit from the previous child cannot disconnect its replacement',async()=>{const backend=await supervisor('normal');await backend.start();const old=(backend as any).child;await backend.stop();await backend.start();try{old.emit('exit',0,null);expect(backend.status.state).toBe('ready');expect(await backend.request('/v1/health')).toHaveProperty('protocol_version','1.0');}finally{await backend.stop();}});
  it('a failed tree cleanup is recorded and blocks a duplicate launch',async()=>{const backend=await supervisor('normal');await backend.start();const options=(backend as any).options;options.spawnTreeKiller=()=>spawn(process.execPath,['-e','process.exit(1)'],{windowsHide:true,stdio:'ignore'});options.terminationTimeoutMs=100;try{await expect(backend.stop()).rejects.toThrow('退出尚未确认');expect(JSON.parse(await readFile(join(options.dataRoot,'desktop-recovery.json'),'utf8')).cleanup_confirmed).toBe(false);await expect(backend.start()).rejects.toThrow('无法重复启动');}finally{options.spawnTreeKiller=undefined;options.terminationTimeoutMs=1500;await backend.stop();}});
  it('does not forward provider or renderer secrets to Python',()=>{process.env.DESKTOP_SECRET_CANARY='secret';process.env.ANTHROPIC_API_KEY='secret';const env=childEnvironment('local-token','instance');expect(env.DESKTOP_SECRET_CANARY).toBeUndefined();expect(env.ANTHROPIC_API_KEY).toBeUndefined();expect(env.WORKBENCH_API_TOKEN).toBe('local-token');delete process.env.DESKTOP_SECRET_CANARY;delete process.env.ANTHROPIC_API_KEY;});
});
