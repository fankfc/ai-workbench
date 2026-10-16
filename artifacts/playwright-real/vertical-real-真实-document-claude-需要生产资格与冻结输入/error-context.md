# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: vertical-real.spec.ts >> 真实 document / claude 需要生产资格与冻结输入
- Location: tests\e2e\vertical-real.spec.ts:8:70

# Error details

```
Error: 真实场景未通过：claude 指导模型缺少生产资格；GLM 执行模型缺少生产资格。未发送任务，模型调用为 0。
```

# Test source

```ts
  1  | import { test,expect } from '@playwright/test';
  2  | import { launchDesktop } from '../support/electron-fixture';
  3  | import { readFile,mkdtemp,writeFile } from 'node:fs/promises';
  4  | import { createHash } from 'node:crypto';
  5  | import { tmpdir } from 'node:os';
  6  | import { resolve,join } from 'node:path';
  7  | const domains=['code','paper','document','composite'];
  8  | for(const domain of domains)for(const family of ['claude','gpt'])test(`真实 ${domain} / ${family} 需要生产资格与冻结输入`,async({},testInfo)=>{
  9  |   if(process.env.AIBROKER_REAL_PROVIDERS!=='1')throw new Error('真实场景未通过：缺少 AIBROKER_REAL_PROVIDERS=1 显式开关。');
  10 |   const frozen=JSON.parse(await readFile(resolve('docs/acceptance/vertical-scenarios.json'),'utf8'));
  11 |   const scenario=frozen.scenarios.find((value:any)=>value.domain===domain);expect(scenario?.provider_mode).toBe('real');expect(scenario.budget_tokens).toBe(300000);expect(scenario.reserved_a_tokens).toBe(60000);expect(scenario.budget_seconds).toBe(480);
  12 |   for(const input of scenario.inputs){const bytes=await readFile(resolve(input.path));expect(createHash('sha256').update(bytes).digest('hex'),`冻结输入 ${input.path}`).toBe(input.sha256);}
  13 |   const userData=process.env.AIBROKER_REAL_USER_DATA?resolve(process.env.AIBROKER_REAL_USER_DATA):await mkdtemp(join(tmpdir(),'workbench-qualified-real-'));
  14 |   const {app,page}=await launchDesktop(userData,'real');let calls=0;
  15 |   try {
  16 |     const status=await page.evaluate(()=>window.workbench.status());const settings=await page.evaluate(()=>window.workbench.getSettings());
  17 |     const qualified=settings.connections.filter(value=>value.provider_mode==='real'&&value.available&&value.enabled&&value.identity_status==='verified'&&value.connection_version&&value.model_id);
  18 |     const a=qualified.find(value=>value.role==='A'&&value.family===family);const b=qualified.find(value=>value.role==='B'&&value.family==='glm');
  19 |     const blockers=[...(status.provider_mode!=='real'?['后端不是真实模式']:[]),...(!a?[`${family} 指导模型缺少生产资格`]:[]),...(!b?['GLM 执行模型缺少生产资格']:[])];
  20 |     await writeFile(testInfo.outputPath('real-preflight.json'),JSON.stringify({domain,family,provider_mode:status.provider_mode,qualified_profiles:qualified.map(value=>({id:value.id,role:value.role,family:value.family,model_id:value.model_id,connection_version:value.connection_version})),blockers,model_calls:0,status:blockers.length?'BLOCKED':'QUALIFIED'},null,2));
> 21 |     if(blockers.length)throw new Error(`真实场景未通过：${blockers.join('；')}。未发送任务，模型调用为 0。`);
     |                              ^ Error: 真实场景未通过：claude 指导模型缺少生产资格；GLM 执行模型缺少生产资格。未发送任务，模型调用为 0。
  22 |     // This branch uses only the production bridge and actual public projection.
  23 |     // Missing qualification never selects a demonstration profile or skips a test.
  24 |     const text=await readFile(resolve(scenario.request),'utf8');const cid=await page.evaluate(()=>window.workbench.createConversation({title:'真实验收'}));
  25 |     const task=await page.evaluate(async({cid,text,profile,domain})=>window.workbench.submitTurn({conversationId:cid,text,provider_profile_id:profile.id,connection_version:profile.connection_version!,client_request_id:crypto.randomUUID(),attachment_ids:[],domain:domain==='composite'?'mixed':domain}),{cid:cid.id,text,profile:a!,domain});calls++;
  26 |     await page.evaluate(cid=>{location.hash='/chat/'+cid;},cid.id);
  27 |     await expect(page.locator('.message.assistant')).toBeVisible({timeout:scenario.budget_seconds*1000-15000});
  28 |     const messages=await page.evaluate(cid=>window.workbench.listMessages({conversationId:cid}),cid.id);expect(messages.items.some(value=>value.turn_id===task.turn_id&&value.kind==='answer.published')).toBe(true);
  29 |     await writeFile(testInfo.outputPath('real-result.json'),JSON.stringify({domain,family,model_calls_started:calls,status:'PUBLIC_ANSWER_RECEIVED',acceptance:'Full criterion and independent quality gates remain required'},null,2));
  30 |     throw new Error('真实公开答案已收到；独立 C 标准、附件材料、文档制品与全 A 基线验收尚未完整装配，D040 不可标记通过。');
  31 |   } finally {await app.close();}
  32 | });
  33 | 
```