import { test, expect } from '../support/electron-fixture';
test('internal canaries never cross the public IPC boundary or briefly appear',async({desktop})=>{
  const {page}=desktop;await page.evaluate(()=>{(window as any).observed='';new MutationObserver(()=>{(window as any).observed+=document.body.textContent??'';}).observe(document.body,{subtree:true,childList:true,characterData:true});});
  await page.getByRole('textbox',{name:'消息输入'}).fill('公开回答测试');await page.getByRole('button',{name:'发送',exact:true}).click();await expect(page.locator('.message.user')).toHaveCount(1);
  for(const kind of ['model.delta','tool.delta','translation.delta'])await desktop.emitInternal(kind,'INTERNAL_ENGLISH_CANARY');
  await expect(page.locator('.message.assistant')).toHaveCount(1,{timeout:15000});expect(JSON.stringify(await desktop.getPublicFrames())).not.toContain('INTERNAL_ENGLISH_CANARY');expect(await page.evaluate(()=>(window as any).observed)).not.toContain('INTERNAL_ENGLISH_CANARY');
});
