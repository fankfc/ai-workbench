import { app, BrowserWindow, session, protocol, net } from 'electron';
import { join, resolve, isAbsolute } from 'node:path';
import { readFile, writeFile, rename, unlink } from 'node:fs/promises';
import { randomUUID } from 'node:crypto';
import { pathToFileURL } from 'node:url';
import { BackendSupervisor, runtimeResources } from './backend';
export { UpdateCoordinator } from './update-coordinator';
import { installIpc } from './ipc';
import { localAssetPath } from './local-assets';
import { ExportDirectory } from './export-directory';
protocol.registerSchemesAsPrivileged([{scheme:'workbench',privileges:{standard:true,secure:true,supportFetchAPI:true,corsEnabled:true}}]);
declare const __TEST_BUILD__:boolean;
const userDataArgument=process.argv.find(value=>value.startsWith('--user-data-dir='));
if(userDataArgument)app.setPath('userData',resolve(userDataArgument.slice('--user-data-dir='.length)));
app.setName('协作工作台');
let window:BrowserWindow|undefined;let backend:BackendSupervisor|undefined;let quitting=false;let closeBehavior='quit';let cleanup:(()=>void)|undefined;
const testState:{frames:unknown[];shutdown?:unknown}={frames:[]};
if(__TEST_BUILD__)(globalThis as any).__desktopTest={getPublicFrames:()=>structuredClone(testState.frames),getBackendStatus:()=>backend?.status,getManagedPid:()=>((backend as any)?.child?.pid??null),getServicePid:()=>((backend as any)?.backendPid??null),stopBackend:()=>backend?.stop(),getWindow:()=>window};
const lock=app.requestSingleInstanceLock();
if(!lock)app.quit();
else {
  app.on('second-instance',()=>{if(window){if(window.isMinimized())window.restore();window.show();window.focus();}});
  app.on('activate',()=>{window?.show();window?.focus();});
  app.on('before-quit',event=>{if(!quitting){event.preventDefault();quitting=true;void backend?.stop().catch(()=>{}).finally(()=>{cleanup?.();app.quit();});}});
  app.whenReady().then(async()=>{
    const runtime=runtimeResources(resolve(__dirname,'../../../..'),app.isPackaged,process.resourcesPath);
    const root=runtime.root;
    const providerMode=process.argv.includes('--demo')?'fake':'real';
    const rendererRoot=join(__dirname,'../renderer');const rendererUrl='workbench://desktop/index.html';
    protocol.handle('workbench',request=>{try{if(request.method!=='GET')return new Response(null,{status:405});return net.fetch(pathToFileURL(localAssetPath(rendererRoot,request.url)).href);}catch{return new Response(null,{status:404});}});
    let dataRoot=join(app.getPath('userData'),'workbench');
    const managedConfig=join(app.getPath('userData'),'managed-storage.json');
    const exports=new ExportDirectory(join(app.getPath('userData'),'export-directory.json'));await exports.load();
    try{const config=JSON.parse(await readFile(managedConfig,'utf8'));if(typeof config.dataRoot==='string'&&isAbsolute(config.dataRoot))dataRoot=config.dataRoot;}catch{}
    backend=new BackendSupervisor({root,dataRoot,providerMode,python:runtime.python});
    session.defaultSession.setPermissionRequestHandler((_contents,_permission,callback)=>callback(false));
    window=new BrowserWindow({width:1440,height:900,minWidth:320,minHeight:480,show:false,title:'协作工作台',webPreferences:{preload:join(__dirname,'../preload/index.cjs'),contextIsolation:true,nodeIntegration:false,sandbox:true,webSecurity:true,allowRunningInsecureContent:false}});
    window.removeMenu();
    window.webContents.setWindowOpenHandler(()=>({action:'deny'}));
    window.webContents.on('will-navigate',(event,url)=>{if(url!==rendererUrl)event.preventDefault();});
    window.webContents.on('will-attach-webview',event=>event.preventDefault());
    window.on('close',event=>{if(!quitting&&closeBehavior==='minimize'){event.preventDefault();window?.minimize();}});
    window.on('closed',()=>{window=undefined;});
    cleanup=installIpc(window,backend,rendererUrl,settings=>{if(settings?.preferences?.close_behavior)closeBehavior=settings.preferences.close_behavior;},__TEST_BUILD__?frame=>testState.frames.push(frame):undefined,async destination=>{const temporary=managedConfig+'.'+randomUUID()+'.tmp';try{await writeFile(temporary,JSON.stringify({dataRoot:destination}),{mode:0o600,flag:'wx'});await rename(temporary,managedConfig);}finally{await unlink(temporary).catch(()=>{});}},exports);
    await window.loadURL(rendererUrl);window.show();
    try{await backend.start();}catch{}
  });
  app.on('window-all-closed',()=>app.quit());
}
