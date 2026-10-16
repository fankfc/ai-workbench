/** Private main-process transaction coordinator. No renderer supplies authority.
 * Native signatures, signed manifests, storage, installer and health adapters
 * are trusted ports; real vendor/install receipts remain an external gate.
 */
import { createHash, randomUUID } from 'node:crypto';
import { constants, createReadStream } from 'node:fs';
import { copyFile, lstat, mkdir, open, readFile, readdir, rename, unlink } from 'node:fs/promises';
import { dirname, isAbsolute, join, relative, resolve } from 'node:path';
import { evaluateUpdate, type UpdateInput } from './updates';

export type UpdateManifest=UpdateInput['manifest'];
export type CurrentInstallation=UpdateInput['current']&{packagePath:string;packageSha256:string};
type NativeSignature=Omit<UpdateInput['observed'],'packageSha256'>;
export type UpdatePhase='STAGING'|'VERIFYING'|'QUIESCING'|'BACKING_UP'|'BACKED_UP'|'INSTALLING'|'MIGRATING'|'CHECKING_HEALTH'|'COMMITTING'|'COMMITTED'|'ROLLING_BACK'|'ROLLED_BACK'|'REJECTED'|'BLOCKED';
export type UpdateState='COMMITTED'|'ROLLED_BACK'|'REJECTED'|'INTERRUPTED'|'BLOCKED';
export type UpdateOutcome={state:UpdateState;activeVersion:string;schema:number|null;sequence:number|null;reasons:string[];operationId?:string;manualRecoveryRequired:boolean;message:string};
export interface CoordinatorPorts {
  readCurrent():Promise<CurrentInstallation>;
  verifySignature(path:string):Promise<NativeSignature>;
  /** Verify vendor authentication, binding exact canonical manifest and package. */
  verifyManifest(manifest:UpdateManifest,manifestSha256:string,packageSha256:string):Promise<{authenticated:boolean;manifestSha256:string;packageSha256:string}>;
  quiesce():Promise<{newTasksStopped:boolean;activeWorkStopped:boolean;checkpointsSaved:boolean}>;
  resume():Promise<void>;
  /** Adapter should use D051 create/validate/export and return its owned ZIP. */
  createBackup(current:CurrentInstallation):Promise<{path:string}>;
  verifyBackup(path:string):Promise<{verified:boolean;consistent:boolean;schema:number}>;
  /** These ports settle only after their owned native work has stopped. */
  install(path:string,expected:CurrentInstallation):Promise<{version:string;packageSha256:string}>;
  migrate(expected:CurrentInstallation):Promise<{schema:number}>;
  health(expected:CurrentInstallation):Promise<{healthy:boolean;version:string;schema:number}>;
  /** Atomic authoritative version/schema/sequence store, idempotent on restart. */
  commitCurrent(current:CurrentInstallation):Promise<void>;
  rollbackInstall(path:string,previous:CurrentInstallation):Promise<{version:string;packageSha256:string}>;
  restoreBackup(path:string,previous:CurrentInstallation):Promise<{verified:boolean;schema:number}>;
  /** Private diagnostics/fault-injection hook; never installed as renderer IPC. */
  phaseReached?(phase:UpdatePhase):Promise<void>;
}
export interface CoordinatorConfig {root:string;incomingRoot:string;knownGoodRoot:string;trustedPublisherThumbprints:string[]}
type BackupBinding={relativePath:'backup.zip';sha256:string;schema:number};
type Journal={formatVersion:1;operationId:string;phase:UpdatePhase;previous:CurrentInstallation;manifest:UpdateManifest;manifestSha256:string;candidateSha256:string|null;backup:BackupBinding|null;resumePending:boolean;recoveries:number;reasons:string[];events:{phase:UpdatePhase;at:string}[]};
const phases:UpdatePhase[]=['STAGING','VERIFYING','QUIESCING','BACKING_UP','BACKED_UP','INSTALLING','MIGRATING','CHECKING_HEALTH','COMMITTING','COMMITTED','ROLLING_BACK','ROLLED_BACK','REJECTED','BLOCKED'];
const terminal=new Set<UpdatePhase>(['COMMITTED','ROLLED_BACK','REJECTED']);
const affecting=new Set<UpdatePhase>(['INSTALLING','MIGRATING','CHECKING_HEALTH','COMMITTING','ROLLING_BACK','BLOCKED']);
const rootsInUse=new Set<string>();
const maxBytes=512*1024*1024,maxBackupBytes=256*1024*1024,maxJournalBytes=64*1024,maxEvents=64,maxRecoveries=3,maxOperations=32;
const hex=(value:unknown):value is string=>typeof value==='string'&&/^[a-f0-9]{64}$/.test(value);
class UpdateFault extends Error {constructor(readonly reason:string){super(reason);}}
export class UpdateInterrupted extends Error {constructor(readonly phase:UpdatePhase){super('UPDATE_INTERRUPTED:'+phase);}}
function fault(reason:string):never {throw new UpdateFault(reason);}
function within(path:string,root:string) {const value=relative(resolve(root),resolve(path));return value!==''&&!value.startsWith('..')&&!isAbsolute(value);}
function canonical(value:any):string {if(Array.isArray(value))return '['+value.map(canonical).join(',')+']';if(value&&typeof value==='object')return '{'+Object.keys(value).sort().map(k=>JSON.stringify(k)+':'+canonical(value[k])).join(',')+'}';return JSON.stringify(value);}
const hashObject=(value:unknown)=>createHash('sha256').update(canonical(value)).digest('hex');
function validCurrent(value:any):value is CurrentInstallation {return value&&/^\d+\.\d+\.\d+$/.test(value.version)&&typeof value.channel==='string'&&value.channel.length>0&&Number.isSafeInteger(value.sequence)&&value.sequence>=0&&Number.isSafeInteger(value.schema)&&value.schema>0&&typeof value.packagePath==='string'&&isAbsolute(value.packagePath)&&hex(value.packageSha256);}
function validManifest(value:any):value is UpdateManifest {return value&&Object.keys(value).sort().join(',')==='channel,compatibleRollbackSchemas,minCompatibleVersion,packageSha256,sequence,targetSchema,version'&&typeof value.version==='string'&&typeof value.minCompatibleVersion==='string'&&typeof value.channel==='string'&&Number.isSafeInteger(value.sequence)&&Number.isSafeInteger(value.targetSchema)&&Array.isArray(value.compatibleRollbackSchemas)&&value.compatibleRollbackSchemas.length<=32&&value.compatibleRollbackSchemas.every((v:any)=>Number.isSafeInteger(v)&&v>0)&&hex(value.packageSha256);}
async function noLinks(path:string) {
  let current=resolve(path);
  for(;;){try{if((await lstat(current)).isSymbolicLink())fault('UPDATE_LINK_FORBIDDEN');}catch(error:any){if(error.code!=='ENOENT')throw error;}const parent=dirname(current);if(parent===current)break;current=parent;}
}
async function fileHash(path:string,limit=maxBytes) {
  await noLinks(path);const info=await lstat(path);
  if(!info.isFile()||info.nlink!==1||info.size>limit)fault('UPDATE_FILE_INVALID');
  const digest=createHash('sha256');let count=0;
  for await(const chunk of createReadStream(path)){count+=chunk.length;if(count>limit)fault('UPDATE_FILE_LIMIT');digest.update(chunk);}
  if(count!==info.size)fault('UPDATE_FILE_CHANGED');return digest.digest('hex');
}
async function copyDurably(source:string,target:string) {
  await copyFile(source,target,constants.COPYFILE_EXCL);
  const handle=await open(target,'r+');try{await handle.sync();}finally{await handle.close();}
}

export class UpdateCoordinator {
  private readonly config:CoordinatorConfig;
  constructor(config:CoordinatorConfig,private readonly ports:CoordinatorPorts) {
    if(![config.root,config.incomingRoot,config.knownGoodRoot].every(isAbsolute)||!config.trustedPublisherThumbprints.length||config.trustedPublisherThumbprints.some(p=>typeof p!=='string'||!p))fault('UPDATE_CONFIG_INVALID');
    this.config={root:resolve(config.root),incomingRoot:resolve(config.incomingRoot),knownGoodRoot:resolve(config.knownGoodRoot),trustedPublisherThumbprints:[...config.trustedPublisherThumbprints]};
    if(this.config.root===this.config.incomingRoot||this.config.root===this.config.knownGoodRoot||within(this.config.root,this.config.incomingRoot)||within(this.config.incomingRoot,this.config.root)||within(this.config.root,this.config.knownGoodRoot)||within(this.config.knownGoodRoot,this.config.root))fault('UPDATE_ROOTS_OVERLAP');
  }
  private journalPath(){return join(this.config.root,'update-journal.json');}
  private operation(journal:Journal){return join(this.config.root,'transactions',journal.operationId);}
  private async lock<T>(work:()=>Promise<T>):Promise<T> {
    const key=this.config.root.toLowerCase();if(rootsInUse.has(key))fault('UPDATE_ALREADY_RUNNING');rootsInUse.add(key);
    try{await noLinks(this.config.root);await mkdir(join(this.config.root,'transactions'),{recursive:true});return await work();}finally{rootsInUse.delete(key);}
  }
  private async readJournal():Promise<Journal|null> {
    const path=this.journalPath();await noLinks(path);
    try{const info=await lstat(path);if(!info.isFile()||info.nlink!==1||info.size>maxJournalBytes)fault('UPDATE_JOURNAL_INVALID');const j=JSON.parse(await readFile(path,'utf8'));
      if(j.formatVersion!==1||!/^[a-f0-9]{32}$/.test(j.operationId)||!phases.includes(j.phase)||!validCurrent(j.previous)||!validManifest(j.manifest)||j.manifestSha256!==hashObject(j.manifest)||j.candidateSha256!==null&&!hex(j.candidateSha256)||typeof j.resumePending!=='boolean'||!Number.isSafeInteger(j.recoveries)||j.recoveries<0||j.recoveries>maxRecoveries||!Array.isArray(j.events)||j.events.length>maxEvents||!Array.isArray(j.reasons)||j.reasons.some((r:any)=>typeof r!=='string')||j.backup!==null&&(j.backup.relativePath!=='backup.zip'||!hex(j.backup.sha256)||!Number.isSafeInteger(j.backup.schema)||j.backup.schema!==j.previous.schema))fault('UPDATE_JOURNAL_INVALID');
      await noLinks(this.operation(j));return j;
    }catch(error:any){if(error.code==='ENOENT')return null;throw error;}
  }
  private async save(journal:Journal,phase:UpdatePhase,notify=true) {
    if(journal.events.length>=maxEvents)fault('UPDATE_JOURNAL_LIMIT');journal.phase=phase;journal.events.push({phase,at:new Date().toISOString()});
    const content=JSON.stringify(journal);if(Buffer.byteLength(content)>maxJournalBytes)fault('UPDATE_JOURNAL_LIMIT');
    const temporary=this.journalPath()+'.'+randomUUID()+'.tmp';await noLinks(this.journalPath());
    try{const handle=await open(temporary,'wx',0o600);try{await handle.writeFile(content);await handle.sync();}finally{await handle.close();}await rename(temporary,this.journalPath());}
    finally{await unlink(temporary).catch(()=>{});}
    if(notify)await this.ports.phaseReached?.(phase);
  }
  private async current() {const value=await this.ports.readCurrent();if(!validCurrent(value)||![this.config.root,this.config.knownGoodRoot].some(root=>within(value.packagePath,root)))fault('UPDATE_CURRENT_INVALID');return structuredClone(value);}
  private target(j:Journal):CurrentInstallation {return {version:j.manifest.version,channel:j.manifest.channel,sequence:j.manifest.sequence,schema:j.manifest.targetSchema,packagePath:join(this.operation(j),'candidate.exe'),packageSha256:j.manifest.packageSha256};}
  private async outcome(state:UpdateState,journal:Journal|null,reasons:string[]=[]):Promise<UpdateOutcome> {
    const current=await this.current().catch(()=>null);
    return {state,activeVersion:current?.version??'unknown',schema:current?.schema??null,sequence:current?.sequence??null,reasons,operationId:journal?.operationId,manualRecoveryRequired:state==='BLOCKED',message:state==='COMMITTED'?'更新完成。':state==='ROLLED_BACK'?'更新未完成，已恢复兼容的上一版本与数据。':state==='REJECTED'?'更新未通过核验，当前版本和数据保留。':state==='INTERRUPTED'?'更新已中断，重新启动后将检查恢复进度。':'更新恢复受阻，请保留当前目录和恢复记录。'};
  }
  private async signed(path:string,sha256:string) {
    const observed=await this.ports.verifySignature(path);
    if(observed.signatureStatus!=='Valid'||observed.chainValid!==true||observed.timestampValid!==true||observed.testCertificate!==false)fault('SIGNATURE_UNTRUSTED');
    if(!observed.publisherThumbprint||!this.config.trustedPublisherThumbprints.some(pin=>pin.toUpperCase()===observed.publisherThumbprint.toUpperCase()))fault('PUBLISHER_UNTRUSTED');
    if(await fileHash(path)!==sha256)fault('PACKAGE_HASH_MISMATCH');return {...observed,packageSha256:sha256};
  }
  private async manifest(j:Journal) {
    const receipt=await this.ports.verifyManifest(j.manifest,j.manifestSha256,j.manifest.packageSha256);
    if(receipt.authenticated!==true||receipt.manifestSha256!==j.manifestSha256||receipt.packageSha256!==j.manifest.packageSha256)fault('MANIFEST_AUTHENTICATION_FAILED');
  }
  private async unchanged(j:Journal,allowTarget=false) {
    const current=await this.current();if(hashObject(current)!==hashObject(j.previous)&&(!allowTarget||hashObject(current)!==hashObject(this.target(j))))fault('AUTHORITATIVE_CURRENT_CHANGED');
  }
  private async resumedReject(j:Journal,reasons:string[]) {
    j.reasons=reasons;await this.save(j,'REJECTED',false);return this.resumeTerminal(j);
  }
  private async resumeTerminal(j:Journal):Promise<UpdateOutcome> {
    if(!j.resumePending)return this.outcome(j.phase as UpdateState,j,j.reasons);
    try{
      await this.ports.resume();j.resumePending=false;j.reasons=j.reasons.filter(r=>r!=='TASK_RESUME_FAILED');
      await this.save(j,j.phase,false);return this.outcome(j.phase as UpdateState,j,j.reasons);
    }catch(error){
      // Installation/data authority is already committed. A scheduler failure
      // must never relabel it rejected or replay a completed data restoration.
      j.resumePending=true;
      if(error instanceof UpdateInterrupted)return this.outcome('INTERRUPTED',j,['INTERRUPTED_'+error.phase]);
      if(!j.reasons.includes('TASK_RESUME_FAILED'))j.reasons.push('TASK_RESUME_FAILED');
      await this.save(j,j.phase,false).catch(()=>{});return this.outcome('BLOCKED',j,j.reasons);
    }
  }
  async update(manifest:UpdateManifest,packagePath:string):Promise<UpdateOutcome> {
    return this.lock(async()=>{
      let j:Journal|null=null;
      try{
        const existing=await this.readJournal();if(existing&&(!terminal.has(existing.phase)||existing.resumePending))return this.outcome('BLOCKED',existing,['PENDING_UPDATE_RECOVERY_REQUIRED']);
        const previous=await this.current();if(!validManifest(manifest))fault('MANIFEST_INVALID');
        if((await readdir(join(this.config.root,'transactions'))).length>=maxOperations)fault('UPDATE_OPERATION_LIMIT');
        j={formatVersion:1,operationId:randomUUID().replaceAll('-',''),phase:'STAGING',previous,manifest:structuredClone(manifest),manifestSha256:hashObject(manifest),candidateSha256:null,backup:null,resumePending:false,recoveries:0,reasons:[],events:[]};
        await mkdir(this.operation(j));await this.save(j,'STAGING');
        if(!isAbsolute(packagePath)||!within(packagePath,this.config.incomingRoot))fault('UPDATE_PATH_OUTSIDE_INBOX');
        await fileHash(packagePath);await fileHash(previous.packagePath);
        const staged=join(this.operation(j),'candidate.exe'),predecessor=join(this.operation(j),'previous.exe');
        await copyDurably(packagePath,staged);await copyDurably(previous.packagePath,predecessor);
        j.candidateSha256=await fileHash(staged);if(j.candidateSha256!==manifest.packageSha256)fault('PACKAGE_HASH_MISMATCH');
        if(await fileHash(predecessor)!==previous.packageSha256)fault('ROLLBACK_PACKAGE_HASH_MISMATCH');
        await this.save(j,'VERIFYING');await this.manifest(j);
        const observed=await this.signed(staged,j.candidateSha256);await this.signed(predecessor,previous.packageSha256);
        const early=evaluateUpdate({manifest:j.manifest,current:previous,observed,trustedPublisherThumbprints:this.config.trustedPublisherThumbprints,backup:{consistent:false,verified:false,schema:previous.schema,sha256:''},checkpointsSaved:false});
        const reasons=early.reasons.filter(r=>!['VERIFIED_BACKUP_REQUIRED','TASK_CHECKPOINTS_REQUIRED'].includes(r));if(reasons.length)throw new UpdateFault(reasons.join(','));
        j.resumePending=true;await this.save(j,'QUIESCING');const quiet=await this.ports.quiesce();
        if(quiet.newTasksStopped!==true||quiet.activeWorkStopped!==true||quiet.checkpointsSaved!==true)fault('TASK_CHECKPOINTS_REQUIRED');
        await this.unchanged(j);await this.save(j,'BACKING_UP');
        const created=await this.ports.createBackup(previous);const backupPath=join(this.operation(j),'backup.zip');
        const originalHash=await fileHash(created.path,maxBackupBytes);await copyDurably(created.path,backupPath);
        const backupHash=await fileHash(backupPath,maxBackupBytes);if(originalHash!==backupHash)fault('BACKUP_CHANGED_DURING_COPY');
        const backup=await this.ports.verifyBackup(backupPath);
        const ready=evaluateUpdate({manifest:j.manifest,current:previous,observed,trustedPublisherThumbprints:this.config.trustedPublisherThumbprints,backup:{...backup,sha256:backupHash},checkpointsSaved:quiet.checkpointsSaved});
        if(ready.state!=='READY_FOR_EXTERNAL_INSTALL')throw new UpdateFault(ready.reasons.join(','));
        j.backup={relativePath:'backup.zip',sha256:backupHash,schema:backup.schema};await this.save(j,'BACKED_UP');
        await this.unchanged(j);await this.manifest(j);await this.signed(staged,j.candidateSha256);
        const target=this.target(j);await this.save(j,'INSTALLING');
        const installed=await this.ports.install(staged,target);if(installed.version!==target.version||installed.packageSha256!==target.packageSha256)fault('INSTALL_RECEIPT_MISMATCH');
        await this.save(j,'MIGRATING');const migrated=await this.ports.migrate(target);if(migrated.schema!==target.schema)fault('MIGRATION_SCHEMA_MISMATCH');
        await this.save(j,'CHECKING_HEALTH');const health=await this.ports.health(target);if(health.healthy!==true||health.version!==target.version||health.schema!==target.schema)fault('FIRST_HEALTH_FAILED');
        await this.unchanged(j);await this.save(j,'COMMITTING');await this.ports.commitCurrent(target);
        if(hashObject(await this.current())!==hashObject(target))fault('AUTHORITATIVE_COMMIT_MISMATCH');
        await this.save(j,'COMMITTED',false);return this.resumeTerminal(j);
      }catch(error){
        if(error instanceof UpdateInterrupted)return this.outcome('INTERRUPTED',j,['INTERRUPTED_'+error.phase]);
        const reasons=error instanceof UpdateFault?error.reason.split(','):['UPDATE_OPERATION_FAILED'];
        if(j&&affecting.has(j.phase))return this.rollback(j,reasons);
        if(j)return this.resumedReject(j,reasons);return this.outcome('REJECTED',null,reasons);
      }
    });
  }
  private async rollback(j:Journal,reasons:string[]):Promise<UpdateOutcome> {
    try{
      await this.unchanged(j,true);const quiet=await this.ports.quiesce();if(quiet.newTasksStopped!==true||quiet.activeWorkStopped!==true)fault('ROLLBACK_NOT_QUIESCENT');
      const predecessor=join(this.operation(j),'previous.exe'),backupPath=join(this.operation(j),'backup.zip');
      if(await fileHash(predecessor)!==j.previous.packageSha256)fault('ROLLBACK_PACKAGE_HASH_MISMATCH');
      await this.signed(predecessor,j.previous.packageSha256);
      if(!j.backup||j.backup.schema!==j.previous.schema||await fileHash(backupPath,maxBackupBytes)!==j.backup.sha256)fault('ROLLBACK_BACKUP_HASH_MISMATCH');
      const backup=await this.ports.verifyBackup(backupPath);if(backup.verified!==true||backup.consistent!==true||backup.schema!==j.previous.schema)fault('ROLLBACK_BACKUP_INCOMPATIBLE');
      j.reasons=reasons;await this.save(j,'ROLLING_BACK');
      const installed=await this.ports.rollbackInstall(predecessor,j.previous);if(installed.version!==j.previous.version||installed.packageSha256!==j.previous.packageSha256)fault('ROLLBACK_INSTALL_MISMATCH');
      const restored=await this.ports.restoreBackup(backupPath,j.previous);if(restored.verified!==true||restored.schema!==j.previous.schema)fault('ROLLBACK_SCHEMA_MISMATCH');
      const health=await this.ports.health(j.previous);if(health.healthy!==true||health.version!==j.previous.version||health.schema!==j.previous.schema)fault('ROLLBACK_HEALTH_FAILED');
      await this.ports.commitCurrent(j.previous);if(hashObject(await this.current())!==hashObject(j.previous))fault('ROLLBACK_COMMIT_MISMATCH');
      await this.save(j,'ROLLED_BACK',false);return this.resumeTerminal(j);
    }catch(error){
      if(error instanceof UpdateInterrupted)return this.outcome('INTERRUPTED',j,['INTERRUPTED_'+error.phase]);
      j.reasons=[...reasons,error instanceof UpdateFault?error.reason:'ROLLBACK_OPERATION_FAILED'];
      await this.save(j,'BLOCKED',false).catch(()=>{});return this.outcome('BLOCKED',j,j.reasons);
    }
  }
  async recover():Promise<UpdateOutcome|null> {
    return this.lock(async()=>{
      let j:Journal|null=null;
      try{
        j=await this.readJournal();if(!j)return null;
        if(terminal.has(j.phase)&&!j.resumePending)return this.outcome(j.phase as UpdateState,j,j.reasons);
        if(j.recoveries>=maxRecoveries)return this.outcome('BLOCKED',j,['RECOVERY_ATTEMPTS_EXHAUSTED']);
        j.recoveries++;await this.save(j,j.phase,false);
        if(terminal.has(j.phase))return this.resumeTerminal(j);
        if(affecting.has(j.phase))return this.rollback(j,['INTERRUPTED_UPDATE_RECOVERY']);
        await this.unchanged(j);return this.resumedReject(j,['INTERRUPTED_BEFORE_INSTALL']);
      }catch(error){return this.outcome('BLOCKED',j,[error instanceof UpdateFault?error.reason:'RECOVERY_JOURNAL_INVALID']);}
    });
  }
}
