import { describe, expect, it } from 'vitest';
// 本文件用例驱动真实端口与文件系统更新流程；时间预算按机器实际延迟放宽，被验证的回滚/恢复行为不变。
import { vi } from 'vitest';
vi.setConfig({testTimeout:20000});
import { mkdtemp, mkdir, readFile, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { createHash, generateKeyPairSync, sign, verify } from 'node:crypto';
import { UpdateCoordinator, UpdateInterrupted, type CoordinatorPorts, type CurrentInstallation, type UpdatePhase, type UpdateManifest } from '../../apps/desktop/src/main/update-coordinator';

const sha=(value:Buffer|string)=>createHash('sha256').update(value).digest('hex');
const publisher='A'.repeat(40);
async function fixture(options:{fault?:string;interrupt?:UpdatePhase;signature?:Partial<any>;manifest?:Partial<UpdateManifest>}={}) {
  const root=await mkdtemp(join(tmpdir(),'update-coordinator-'));const incoming=join(root,'incoming');const known=join(root,'known-good');const area=join(root,'update');
  await mkdir(incoming);await mkdir(known);
  const previous=join(known,'previous.exe'),candidate=join(incoming,'candidate.exe');
  await writeFile(previous,'signed predecessor bytes');await writeFile(candidate,'signed candidate bytes');
  const before:CurrentInstallation={version:'1.0.0',channel:'stable',sequence:10,schema:3,packagePath:previous,packageSha256:sha('signed predecessor bytes')};
  const state=join(root,'current.json'),program=join(root,'installed.exe'),data=join(root,'data.json');
  await writeFile(state,JSON.stringify(before));await writeFile(program,'signed predecessor bytes');await writeFile(data,JSON.stringify({schema:3,content:'private preserved Chinese source 中文'}));
  const calls:string[]=[];let frozen=false;let interrupted=false;
  const manifest={version:'1.1.0',channel:'stable',sequence:11,minCompatibleVersion:'1.0.0',packageSha256:sha('signed candidate bytes'),targetSchema:4,compatibleRollbackSchemas:[3],...options.manifest};
  const manifestBytes=(value:UpdateManifest)=>Buffer.from(JSON.stringify(value,Object.keys(value).sort()));
  const keys=generateKeyPairSync('ed25519');const manifestSignature=sign(null,manifestBytes(manifest),keys.privateKey);
  const ports:CoordinatorPorts={
    readCurrent:async()=>JSON.parse(await readFile(state,'utf8')),
    verifySignature:async path=>{calls.push('signature:'+path.split(/[\\/]/).at(-1));return {signatureStatus:'Valid',publisherThumbprint:publisher,chainValid:true,timestampValid:true,testCertificate:false,...(path.endsWith('candidate.exe')?options.signature:{})};},
    verifyManifest:async candidate=>({authenticated:verify(null,manifestBytes(candidate),keys.publicKey,manifestSignature),manifestSha256:sha(manifestBytes(candidate)),packageSha256:candidate.packageSha256}),
    quiesce:async()=>{calls.push('quiesce');frozen=true;return {newTasksStopped:true,activeWorkStopped:true,checkpointsSaved:options.fault!=='checkpoint'};},
    resume:async()=>{calls.push('resume');frozen=false;},
    createBackup:async()=>{calls.push('backup');const path=join(root,'backup.zip');await writeFile(path,await readFile(data));return {path};},
    verifyBackup:async path=>{calls.push('verify-backup');const snapshot=JSON.parse(await readFile(path,'utf8'));return {verified:options.fault!=='backup',consistent:true,schema:snapshot.schema};},
    install:async(path,expected)=>{calls.push('install');const unpacked=join(root,'unpacked-candidate.exe');await writeFile(unpacked,await readFile(path));if(options.fault==='unpack_interrupt')throw new UpdateInterrupted('INSTALLING');await writeFile(program,await readFile(unpacked));if(options.fault==='replace_interrupt')throw new UpdateInterrupted('INSTALLING');if(options.fault==='install')throw new Error('injected install failure');return {version:expected.version,packageSha256:sha(await readFile(program))};},
    migrate:async expected=>{calls.push('migrate');const old=JSON.parse(await readFile(data,'utf8'));await writeFile(data,JSON.stringify({...old,schema:expected.schema}));if(options.fault==='migration')throw new Error('injected migration failure');return {schema:expected.schema};},
    health:async expected=>{calls.push('health:'+expected.version);const observed=JSON.parse(await readFile(data,'utf8'));const actualVersion=(await readFile(program,'utf8'))==='signed candidate bytes'?'1.1.0':'1.0.0';return {healthy:options.fault!=='health'||expected.version==='1.0.0',version:actualVersion,schema:observed.schema};},
    commitCurrent:async current=>{calls.push('commit:'+current.version);await writeFile(state,JSON.stringify(current));},
    rollbackInstall:async(path,expected)=>{calls.push('rollback-install');if(options.fault==='rollback')throw new Error('rollback blocked');await writeFile(program,await readFile(path));return {version:expected.version,packageSha256:sha(await readFile(program))};},
    restoreBackup:async(path,expected)=>{calls.push('restore-backup');await writeFile(data,await readFile(path));return {verified:true,schema:JSON.parse(await readFile(data,'utf8')).schema};},
    phaseReached:async phase=>{if(options.interrupt===phase&&!interrupted){interrupted=true;throw new UpdateInterrupted(phase);}},
  };
  const config={root:area,incomingRoot:incoming,knownGoodRoot:known,trustedPublisherThumbprints:[publisher]};
  const coordinator=new UpdateCoordinator(config,ports);
  return {root,area,coordinator,ports,config,manifest,candidate,before,state,program,data,calls,get frozen(){return frozen;}};
}

describe('recoverable main-process update coordinator with private trusted ports',()=>{
  it('uses actual staged hashes/native observations and commits only after health',async()=>{
    const f=await fixture();const result=await f.coordinator.update(f.manifest,f.candidate);
    expect(result.state).toBe('COMMITTED');expect(result.activeVersion).toBe('1.1.0');
    expect(await readFile(f.program,'utf8')).toBe('signed candidate bytes');
    expect(JSON.parse(await readFile(f.data,'utf8')).schema).toBe(4);
    expect(f.calls.indexOf('commit:1.1.0')).toBeGreaterThan(f.calls.indexOf('health:1.1.0'));expect(f.frozen).toBe(false);
    const journal=JSON.parse(await readFile(join(f.area,'update-journal.json'),'utf8'));
    expect(journal.backup.sha256).toMatch(/^[a-f0-9]{64}$/);expect(journal.backup.schema).toBe(3);expect(journal.phase).toBe('COMMITTED');
  });
  it.each(['signature','publisher','hash','replay','downgrade','channel','schema','checkpoint','backup'])('rejects %s without changing authoritative version/schema/sequence or data',async fault=>{
    const f=await fixture({fault,signature:fault==='signature'?{signatureStatus:'NotSigned'}:fault==='publisher'?{publisherThumbprint:'B'.repeat(40)}:{}});
    if(fault==='hash')await writeFile(f.candidate,'tampered candidate');
    if(fault==='replay')f.manifest.sequence=10;if(fault==='downgrade')f.manifest.version='0.9.0';if(fault==='channel')f.manifest.channel='beta';if(fault==='schema')f.manifest.compatibleRollbackSchemas=[2];
    const before=await readFile(f.data);const result=await f.coordinator.update(f.manifest,f.candidate);
    expect(result.state).toBe('REJECTED');expect(JSON.parse(await readFile(f.state,'utf8'))).toEqual(f.before);expect(await readFile(f.data)).toEqual(before);
    expect(await readFile(f.program,'utf8')).toBe('signed predecessor bytes');expect(f.calls).not.toContain('install');expect(f.frozen).toBe(false);
  });
  it.each(['install','migration','health'])('%s failure restores the trusted predecessor with its matching schema backup',async fault=>{
    const f=await fixture({fault});const before=await readFile(f.data);const result=await f.coordinator.update(f.manifest,f.candidate);
    expect(result.state).toBe('ROLLED_BACK');expect(result.activeVersion).toBe('1.0.0');expect(result.schema).toBe(3);
    expect(await readFile(f.data)).toEqual(before);expect(await readFile(f.program,'utf8')).toBe('signed predecessor bytes');expect(JSON.parse(await readFile(f.state,'utf8'))).toEqual(f.before);expect(f.frozen).toBe(false);
  });
  it.each(['STAGING','VERIFYING','QUIESCING','BACKING_UP','INSTALLING','MIGRATING','CHECKING_HEALTH','COMMITTING'] as UpdatePhase[])('recovers an interrupted %s journal without accepting a network downgrade',async phase=>{
    const f=await fixture({interrupt:phase});const before=await readFile(f.data);const interrupted=await f.coordinator.update(f.manifest,f.candidate);
    expect(interrupted.state).toBe('INTERRUPTED');
    const recovered=await new UpdateCoordinator(f.config,f.ports).recover();
    expect(['REJECTED','ROLLED_BACK']).toContain(recovered?.state);expect(await readFile(f.data)).toEqual(before);
    expect(JSON.parse(await readFile(f.state,'utf8'))).toEqual(f.before);expect(await readFile(f.program,'utf8')).toBe('signed predecessor bytes');expect(f.frozen).toBe(false);
  });
  it('refuses rollback when the locally captured predecessor or backup was tampered',async()=>{
    const f=await fixture({interrupt:'MIGRATING'});await f.coordinator.update(f.manifest,f.candidate);
    const journal=JSON.parse(await readFile(join(f.area,'update-journal.json'),'utf8'));
    await writeFile(join(f.area,'transactions',journal.operationId,'previous.exe'),'tampered previous');
    const result=await new UpdateCoordinator(f.config,f.ports).recover();
    expect(result?.state).toBe('BLOCKED');expect(result?.reasons).toContain('ROLLBACK_PACKAGE_HASH_MISMATCH');
    expect(f.calls).not.toContain('rollback-install');expect(f.frozen).toBe(true);expect(JSON.parse(await readFile(f.state,'utf8'))).toEqual(f.before);
  });
  it('retains interrupted rollback progress and recovers it idempotently',async()=>{
    const f=await fixture({fault:'health',interrupt:'ROLLING_BACK'});const interrupted=await f.coordinator.update(f.manifest,f.candidate);
    expect(interrupted.state).toBe('INTERRUPTED');const result=await new UpdateCoordinator(f.config,f.ports).recover();
    expect(result?.state).toBe('ROLLED_BACK');expect(JSON.parse(await readFile(f.state,'utf8'))).toEqual(f.before);expect(f.frozen).toBe(false);
  });
  it('rejects a staged path outside the private download directory',async()=>{
    const f=await fixture();const outside=join(f.root,'outside.exe');await writeFile(outside,'signed candidate bytes');
    const result=await f.coordinator.update(f.manifest,outside);expect(result.state).toBe('REJECTED');expect(f.calls).not.toContain('install');
    expect(JSON.parse(await readFile(f.state,'utf8'))).toEqual(f.before);
  });
  it('rejects a relabeled manifest even when the candidate Authenticode port says Valid',async()=>{
    const f=await fixture();f.manifest.version='9.9.9';f.manifest.sequence=999;
    const result=await f.coordinator.update(f.manifest,f.candidate);
    expect(result.state).toBe('REJECTED');expect(result.reasons).toContain('MANIFEST_AUTHENTICATION_FAILED');
    expect(f.calls).not.toContain('quiesce');expect(f.calls).not.toContain('install');expect(JSON.parse(await readFile(f.state,'utf8'))).toEqual(f.before);
  });
  it.each([{manifest:{sequence:10},reason:'MANIFEST_REPLAY'},
    {manifest:{version:'0.9.0'},reason:'NETWORK_DOWNGRADE_OR_REPLAY'},
    {manifest:{channel:'beta'},reason:'CHANNEL_MISMATCH'},
    {manifest:{compatibleRollbackSchemas:[2]},reason:'SCHEMA_ROLLBACK_INCOMPATIBLE'}])('rejects an authenticated old/incompatible vendor fixture: $reason',async item=>{
    const f=await fixture({manifest:item.manifest});const result=await f.coordinator.update(f.manifest,f.candidate);
    expect(result.state).toBe('REJECTED');expect(result.reasons).toContain(item.reason);expect(f.calls).not.toContain('install');
    expect(JSON.parse(await readFile(f.state,'utf8'))).toEqual(f.before);
  });
  it('refuses a tampered captured backup before any rollback data write',async()=>{
    const f=await fixture({interrupt:'MIGRATING'});await f.coordinator.update(f.manifest,f.candidate);
    const j=JSON.parse(await readFile(join(f.area,'update-journal.json'),'utf8'));
    await writeFile(join(f.area,'transactions',j.operationId,'backup.zip'),'tampered saved data');
    const result=await new UpdateCoordinator(f.config,f.ports).recover();expect(result?.state).toBe('BLOCKED');expect(result?.reasons).toContain('ROLLBACK_BACKUP_HASH_MISMATCH');
    expect(f.calls).not.toContain('restore-backup');expect(f.calls).not.toContain('rollback-install');expect(f.frozen).toBe(true);
  });
  it('rejects a corrupt journal without installing or restoring data',async()=>{
    const f=await fixture();await mkdir(f.area);await writeFile(join(f.area,'update-journal.json'),'{bad json');
    const before=await readFile(f.data);expect((await f.coordinator.recover())?.state).toBe('BLOCKED');
    expect(await readFile(f.data)).toEqual(before);expect(f.calls).not.toContain('install');expect(f.calls).not.toContain('restore-backup');
  });
  it.each(['committed','rejected','rolled-back'])('preserves %s authority and retries only task resume after a terminal resume failure',async terminal=>{
    const f=await fixture({fault:terminal==='rejected'?'checkpoint':terminal==='rolled-back'?'health':undefined});
    let attempts=0;const resume=f.ports.resume;f.ports.resume=async()=>{if(++attempts===1)throw new Error('task resume failed');await resume();};
    const result=await f.coordinator.update(f.manifest,f.candidate);
    expect(result.state).toBe('BLOCKED');expect(result.reasons).toContain('TASK_RESUME_FAILED');
    const phase=terminal==='committed'?'COMMITTED':terminal==='rejected'?'REJECTED':'ROLLED_BACK';
    const journal=JSON.parse(await readFile(join(f.area,'update-journal.json'),'utf8'));
    expect(journal.phase).toBe(phase);expect(journal.resumePending).toBe(true);
    const current=JSON.parse(await readFile(f.state,'utf8'));
    expect(current.version).toBe(terminal==='committed'?'1.1.0':'1.0.0');
    const calls=f.calls.filter(v=>['install','migrate','rollback-install','restore-backup'].includes(v)).length;
    const changed=JSON.parse(await readFile(f.data,'utf8'));changed.content='operator data after completed transaction';await writeFile(f.data,JSON.stringify(changed));
    const restarted=new UpdateCoordinator(f.config,f.ports);
    expect((await restarted.update(f.manifest,f.candidate)).state).toBe('BLOCKED');
    const recovered=await restarted.recover();expect(recovered?.state).toBe(phase);
    expect(JSON.parse(await readFile(f.state,'utf8'))).toEqual(current);expect(JSON.parse(await readFile(f.data,'utf8')).content).toBe('operator data after completed transaction');
    expect(f.calls.filter(v=>['install','migrate','rollback-install','restore-backup'].includes(v)).length).toBe(calls);
    expect(attempts).toBe(2);expect(f.frozen).toBe(false);
  });
  it('recovers a crash during task resume after committed authority without reinstalling or restoring',async()=>{
    const f=await fixture();let once=true;const resume=f.ports.resume;
    f.ports.resume=async()=>{if(once){once=false;throw new UpdateInterrupted('COMMITTED');}await resume();};
    expect((await f.coordinator.update(f.manifest,f.candidate)).state).toBe('INTERRUPTED');
    expect(JSON.parse(await readFile(join(f.area,'update-journal.json'),'utf8')).phase).toBe('COMMITTED');
    expect((await new UpdateCoordinator(f.config,f.ports).recover())?.state).toBe('COMMITTED');
    expect(f.calls.filter(c=>c==='install')).toHaveLength(1);expect(f.calls).not.toContain('restore-backup');
  });
  it('bounds resume recovery retries and retains the committed version for manual recovery',async()=>{
    const f=await fixture();let attempts=0;f.ports.resume=async()=>{attempts++;throw new Error('resume still blocked');};
    expect((await f.coordinator.update(f.manifest,f.candidate)).state).toBe('BLOCKED');
    const restarted=new UpdateCoordinator(f.config,f.ports);
    for(let i=0;i<3;i++)expect((await restarted.recover())?.state).toBe('BLOCKED');
    const exhausted=await restarted.recover();expect(exhausted?.reasons).toContain('RECOVERY_ATTEMPTS_EXHAUSTED');expect(attempts).toBe(4);
    expect(JSON.parse(await readFile(f.state,'utf8')).version).toBe('1.1.0');
  });
  it.each(['unpack_interrupt','replace_interrupt'])('recovers the actual filesystem cutpoint %s within the trusted installer transaction',async fault=>{
    const f=await fixture({fault});const before=await readFile(f.data);expect((await f.coordinator.update(f.manifest,f.candidate)).state).toBe('INTERRUPTED');
    expect(await readFile(join(f.root,'unpacked-candidate.exe'),'utf8')).toBe('signed candidate bytes');
    const result=await new UpdateCoordinator(f.config,f.ports).recover();expect(result?.state).toBe('ROLLED_BACK');
    expect(await readFile(f.data)).toEqual(before);expect(await readFile(f.program,'utf8')).toBe('signed predecessor bytes');expect(JSON.parse(await readFile(f.state,'utf8'))).toEqual(f.before);
  });
  it('excludes a competing coordinator while a native operation is still in flight',async()=>{
    const f=await fixture();let entered!:()=>void,release!:()=>void;const reached=new Promise<void>(r=>entered=r),gate=new Promise<void>(r=>release=r);const install=f.ports.install;
    f.ports.install=async(path,expected)=>{entered();await gate;return install(path,expected);};
    const pending=f.coordinator.update(f.manifest,f.candidate);await reached;
    await expect(new UpdateCoordinator(f.config,f.ports).recover()).rejects.toThrow('UPDATE_ALREADY_RUNNING');release();
    expect((await pending).state).toBe('COMMITTED');
  });
  it('rolls back a failed authoritative commit even after the target pointer was written',async()=>{
    const f=await fixture();const commit=f.ports.commitCurrent;f.ports.commitCurrent=async current=>{await commit(current);if(current.version==='1.1.0')throw new Error('commit receipt failed after atomic write');};
    const result=await f.coordinator.update(f.manifest,f.candidate);expect(result.state).toBe('ROLLED_BACK');
    expect(JSON.parse(await readFile(f.state,'utf8'))).toEqual(f.before);expect(JSON.parse(await readFile(f.data,'utf8')).schema).toBe(3);
  });
});
