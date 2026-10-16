import { spawn, execFile, type ChildProcess } from 'node:child_process';
import { randomBytes, randomUUID } from 'node:crypto';
import { createInterface } from 'node:readline';
import { join } from 'node:path';
import { mkdir, writeFile } from 'node:fs/promises';
import { acceptHandshake } from '../shared/validation';
import type { BackendStatus } from '../shared/desktop-bridge';

type Options={root:string;dataRoot:string;providerMode:'real'|'fake';timeoutMs?:number;python?:string;spawnProcess?:typeof spawn;fetchRequest?:typeof fetch;spawnTreeKiller?:typeof spawn;terminationTimeoutMs?:number};
export function runtimeResources(developmentRoot:string,packaged:boolean,resourcesPath:string):{root:string;python?:string} {
  return packaged ? {root:resourcesPath,python:join(resourcesPath,'python','python.exe')} : {root:developmentRoot};
}
export function childEnvironment(token:string,instance:string):NodeJS.ProcessEnv {
  const env:NodeJS.ProcessEnv={};
  for(const key of ['PATH','SystemRoot','WINDIR','TEMP','TMP','USERPROFILE','APPDATA','LOCALAPPDATA','PROGRAMFILES','PROGRAMFILES(X86)','COMSPEC'])if(process.env[key])env[key]=process.env[key];
  return {...env,PYTHONUTF8:'1',PYTHONUNBUFFERED:'1',WORKBENCH_API_TOKEN:token,WORKBENCH_INSTANCE_ID:instance};
}
export class BackendSupervisor {
  private token=randomBytes(32).toString('hex');
  private child?:ChildProcess;
  private base='';
  private stopping=false;
  private generation=0;
  private starting?:Promise<BackendStatus>;
  private stopTask?:Promise<void>;
  private attempts=0;
  private backendPid?:number;
  status:BackendStatus;
  constructor(private options:Options) {this.status={state:'offline',provider_mode:options.providerMode,message:'本地服务尚未连接。'};}
  async start():Promise<BackendStatus> {
    if(this.stopTask || this.status.state==='stopping')throw new Error('本地服务正在退出，请稍后重试。');
    if(this.starting)return this.starting;
    if(this.status.state==='ready')return this.status;
    if(this.child && [this.child.pid,this.backendPid].some(pid=>this.alive(pid)))throw new Error('旧的托管服务退出尚未确认，无法重复启动。请重试退出应用。');
    if(this.attempts>=3)throw new Error('本地服务多次启动失败。请重新打开应用。');
    this.starting=this.launch().finally(()=>{this.starting=undefined;});
    return this.starting;
  }
  private async launch():Promise<BackendStatus> {
    const generation=this.generation;
    this.attempts++;this.stopping=false;
    this.status={...this.status,state:'starting',message:'正在连接本地服务…'};
    await mkdir(this.options.dataRoot,{recursive:true});
    if(generation!==this.generation){this.attempts--;throw new Error('本地服务启动已取消。');}
    const instance=randomUUID();
    const executable=this.options.python ?? join(this.options.root,'services/orchestrator/.venv',process.platform==='win32'?'Scripts/python.exe':'bin/python');
    const child=(this.options.spawnProcess??spawn)(executable,['-m','app.api.launcher','--host','127.0.0.1','--port','0','--data-root',this.options.dataRoot,'--provider-mode',this.options.providerMode],{cwd:join(this.options.root,'services/orchestrator'),env:childEnvironment(this.token,instance),windowsHide:true,stdio:['ignore','pipe','pipe']});
    this.child=child;
    child.stderr?.on('data',()=>{}); // raw backend logs never cross the renderer boundary
    child.on('exit',()=>{if(this.child!==child)return;this.base='';if(!this.stopping)this.status={...this.status,state:'offline',message:'本地服务已断开。草稿已保存，可以重试连接。'};});
    try {
      const ready=await new Promise<any>((resolve,reject)=>{
        let settled=false;
        const lines=createInterface({input:child.stdout!});
        const timeout=setTimeout(()=>finish(new Error('本地服务启动超时。')),this.options.timeoutMs??20000);
        const earlyExit=()=>finish(new Error('本地服务在就绪前退出。'));
        const failed=()=>finish(new Error('无法启动本地服务。'));
        const finish=(error?:Error,value?:any)=>{if(settled)return;settled=true;clearTimeout(timeout);lines.close();child.off('exit',earlyExit);child.off('error',failed);error?reject(error):resolve(value);};
        lines.on('line',async line=>{if(line.length>4096)return;try{const value=JSON.parse(line);if(acceptHandshake(value,instance,value.pid) && await this.ownsProcess(value.pid,child.pid!)){this.backendPid=value.pid;finish(undefined,value);}}catch{}});
        child.once('exit',earlyExit);child.once('error',failed);
      });
      if(generation!==this.generation)throw new Error('本地服务启动已取消。');
      this.base=`http://127.0.0.1:${ready.port}`;
      const health=await this.request<any>('/v1/health','GET',undefined,Math.min(this.options.timeoutMs??5000,5000));
      if(generation!==this.generation)throw new Error('本地服务启动已取消。');
      if(health.instance_id!==instance || health.pid!==this.backendPid || health.protocol_version!=='1.0' || health.provider_mode!==this.options.providerMode || child.exitCode!==null)throw new Error('本地服务身份核验失败。');
      this.status={...this.status,state:'ready',message:this.options.providerMode==='fake'?'演示模式：使用模拟模型响应。':'本地服务已连接。'};
      this.attempts=0;
      return this.status;
    } catch(error) {const cleaned=await this.terminate();if(generation!==this.generation)this.attempts=Math.max(0,this.attempts-1);const message=error instanceof Error?error.message:'本地服务连接失败。';const failure=cleaned?message:message+' 托管服务退出尚未确认，无法重复启动。';if(!this.stopTask)this.status={...this.status,state:'offline',message:failure};throw new Error(failure);}
  }
  private async ownsProcess(candidate:number,owner:number):Promise<boolean> {
    if(candidate===owner)return true;
    if(process.platform!=='win32' || !Number.isInteger(candidate) || candidate<1)return false;
    const powershell=join(process.env.SystemRoot??'C:/Windows','System32/WindowsPowerShell/v1.0/powershell.exe');
    // Windows virtual-environment Python has a redirector parent. Only its direct
    // child may announce readiness; an unrelated PID or occupied port is rejected.
    const command=`$candidateProcess = Get-CimInstance Win32_Process -Filter 'ProcessId=${candidate}'; if ($candidateProcess.ParentProcessId -eq ${owner}) { 'owned' }`;
    return new Promise(resolve=>execFile(powershell,['-NoLogo','-NoProfile','-NonInteractive','-Command',command],{windowsHide:true,timeout:10000},(error,stdout)=>resolve(!error&&stdout.trim()==='owned')));
  }
  async request<T>(path:string,method='GET',body?:unknown,timeoutMs=10000):Promise<T> {
    const response=await this.response(path,method,body,timeoutMs);
    return await response.json() as T;
  }
  async response(path:string,method='GET',body?:unknown,timeoutMs=10000,extraHeaders:Record<string,string>={}):Promise<Response> {
    if(!this.base || !path.startsWith('/v1/') || path.includes('://') || path.includes('..'))throw new Error('本地服务尚未就绪。');
    const headers={Authorization:`Bearer ${this.token}`,...extraHeaders};
    let content:BodyInit|undefined;
    if(body instanceof Uint8Array)content=body as BodyInit;
    else if(body!==undefined){content=JSON.stringify(body);Object.assign(headers,{'Content-Type':'application/json'});}
    try {
      const response=await (this.options.fetchRequest??fetch)(this.base+path,{method,headers,body:content,signal:AbortSignal.timeout(timeoutMs),redirect:'error'});
      if(!response.ok){let message='本地操作暂不可用，请稍后重试。';try{const error=await response.json();if(typeof error.detail==='string' && /[\u4e00-\u9fff]/.test(error.detail) && error.detail.length<300)message=error.detail;}catch{}throw new Error(message);}
      return response;
    }catch(error){if(error instanceof Error && /[\u4e00-\u9fff]/.test(error.message))throw error;throw new Error('本地服务暂时无法连接。草稿已保存，请重试。');}
  }
  stop():Promise<void> {
    if(this.stopTask)return this.stopTask;
    this.generation++;
    this.stopping=true;this.status={...this.status,state:'stopping',message:'正在保存当前进度…'};
    this.stopTask=this.finishStop().finally(()=>{this.stopTask=undefined;});
    return this.stopTask;
  }
  private async finishStop():Promise<void> {
    let saved=false;
    try{const checkpoint=await this.request<any>('/v1/checkpoint','POST',{},2000);saved=checkpoint.saved===true;}catch{}
    let journalSaved=true;
    const record=async(cleaned:boolean)=>{try{await writeFile(join(this.options.dataRoot,'desktop-recovery.json'),JSON.stringify({checkpoint_confirmed:saved,cleanup_confirmed:cleaned,time:new Date().toISOString()}));}catch{journalSaved=false;}};
    await record(false);
    const cleaned=await this.terminate();
    await record(cleaned);
    this.status={...this.status,state:'offline',message:!cleaned?'托管服务退出尚未确认，无法重复启动。'+(journalSaved?'已记录恢复状态，':'恢复记录尚未保存，')+'请重试退出应用。':!journalSaved?'本地服务已退出，恢复记录尚未保存。':saved?'当前进度已保存。':'保存尚未确认，下次启动将检查恢复状态。'};
    if(!cleaned)throw new Error(this.status.message);
  }
  async relocateTo(destination:string,persist?:(destination:string)=>Promise<void>):Promise<void> {
    const previous=this.options.dataRoot;
    await this.stop();
    try{await persist?.(destination);this.options.dataRoot=destination;await this.start();}
    catch(error){this.options.dataRoot=previous;await persist?.(previous).catch(()=>{});await this.start().catch(()=>{});throw error;}
  }
  private alive(pid:number|undefined):boolean {if(!pid)return false;try{process.kill(pid,0);return true;}catch{return false;}}
  private processesGone(child:ChildProcess|undefined,pids:(number|undefined)[]):boolean {
    // The owned spawn handle is authoritative for its own exit. On Windows a
    // terminated PID can remain queryable while Node still holds that handle.
    return pids.every(pid=>!pid||(pid===child?.pid?(child.exitCode!==null||child.signalCode!==null):!this.alive(pid)));
  }
  private async terminate():Promise<boolean> {
    const child=this.child;this.base='';
    const pids=[child?.pid,this.backendPid];const timeout=this.options.terminationTimeoutMs??1500;
    if(!child)return this.processesGone(child,pids);
    if(child.exitCode!==null || !child.pid){const cleaned=this.processesGone(child,pids);if(cleaned&&this.child===child){this.child=undefined;this.backendPid=undefined;}return cleaned;}
    const exited=new Promise<void>(resolve=>child.once('exit',()=>resolve()));
    if(process.platform==='win32'){
      // Killing the redirector first loses its descendant relation. Checkpoint
      // precedes this operation; terminate the still-owned tree as one action.
      const taskkill=join(process.env.SystemRoot??'C:/Windows','System32/taskkill.exe');
      await new Promise<void>(resolve=>{const killer=(this.options.spawnTreeKiller??spawn)(taskkill,['/PID',String(child.pid),'/T','/F'],{windowsHide:true,stdio:'ignore'});let settled=false;const finish=()=>{if(settled)return;settled=true;clearTimeout(timer);resolve();};const timer=setTimeout(()=>{killer.kill();finish();},timeout);killer.once('exit',finish);killer.once('error',finish);});
      await Promise.race([exited,new Promise(resolve=>setTimeout(resolve,timeout))]);
      const cleaned=this.processesGone(child,pids);if(cleaned&&this.child===child){this.child=undefined;this.backendPid=undefined;}return cleaned;
    }
    child.kill('SIGTERM');
    const finished=await Promise.race([exited.then(()=>true),new Promise<boolean>(resolve=>setTimeout(()=>resolve(false),timeout))]);
    if(!finished){
      child.kill('SIGKILL');
      await Promise.race([exited,new Promise(resolve=>setTimeout(resolve,timeout))]);
    }
    const cleaned=this.processesGone(child,pids);if(cleaned&&this.child===child){this.child=undefined;this.backendPid=undefined;}return cleaned;
  }
}
