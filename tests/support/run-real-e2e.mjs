import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { dirname,resolve } from 'node:path';
const root=resolve(dirname(fileURLToPath(import.meta.url)),'../..');
const child=spawn(process.execPath,[resolve(root,'node_modules/@playwright/test/cli.js'),'test','--config',resolve(root,'apps/desktop/playwright.real.config.ts'),...process.argv.slice(2)],{cwd:root,env:{...process.env,AIBROKER_REAL_PROVIDERS:'1'},windowsHide:true,stdio:'inherit'});
child.once('error',error=>{process.stderr.write(`真实场景入口未运行：${error.message}\n`);process.exitCode=1;});
child.once('exit',(code,signal)=>{process.exitCode=code??(signal?1:0);});
