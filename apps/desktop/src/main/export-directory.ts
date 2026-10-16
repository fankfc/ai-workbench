import { readFile, writeFile, rename, unlink, access } from 'node:fs/promises';
import { constants } from 'node:fs';
import { basename, isAbsolute } from 'node:path';
import { randomUUID } from 'node:crypto';
export class ExportDirectory {
  private directory:string|undefined;
  constructor(private config:string){}
  async load(){try{const value=JSON.parse(await readFile(this.config,'utf8'));if(typeof value.directory==='string'&&isAbsolute(value.directory))this.directory=value.directory;}catch{}}
  get path(){return this.directory;}
  get status(){return {configured:!!this.directory,label:this.directory?basename(this.directory):'每次保存时选择'};}
  async set(directory?:string){
    if(directory){if(!isAbsolute(directory))throw new Error('目录选择无效。');await access(directory,constants.W_OK);}
    const temporary=this.config+'.'+randomUUID()+'.tmp';
    try{await writeFile(temporary,JSON.stringify({directory:directory??null}),{mode:0o600,flag:'wx'});await rename(temporary,this.config);this.directory=directory;}
    finally{await unlink(temporary).catch(()=>{});}return this.status;
  }
}
