import { _electron, expect } from '@playwright/test';
import { mkdtemp, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
const data = await mkdtemp(join(tmpdir(), 'desktop-code-material-review-'));
const material = join(data, 'project.py');
await writeFile(material, 'def add(a, b):\n    return a + b\n');
const app = await _electron.launch({executablePath:resolve('node_modules/electron/dist/electron.exe'),args:[resolve('apps/desktop/dist-test/main/index.cjs'),`--user-data-dir=${data}`,'--demo'],env:{...process.env,ELECTRON_RUN_AS_NODE:undefined}});
try {
  const page = await app.firstWindow();
  await expect.poll(() => app.evaluate(() => globalThis.__desktopTest.getBackendStatus().state), {timeout:30000}).toBe('ready');
  await app.evaluate(({dialog}, material) => {dialog.showOpenDialog = async () => ({canceled:false,filePaths:[material]});}, material);
  await page.getByRole('button',{name:'添加文件',exact:true}).click();
  await expect(page.locator('.attachment')).toHaveCount(1);
  await page.getByLabel('任务类型').selectOption('code');
  await page.getByLabel('编程需求说明').fill('检查加法语义');
  await page.getByLabel('预期测试命令').fill('python -m pytest');
  await page.getByLabel('工作材料').selectOption({label:'project.py'});
  await page.getByRole('textbox',{name:'消息输入'}).fill('请检查工作材料');
  await page.getByRole('button',{name:'发送',exact:true}).click();
  await expect(page.getByText('材料引用不属于本次任务。',{exact:true})).toBeVisible();
  const result={materialName:'project.py',importedAttachmentCount:await page.locator('.attachment').count(),acceptedMessages:await page.locator('.message.user').count(),error:await page.getByText('材料引用不属于本次任务。',{exact:true}).textContent(),modelCalls:0};
  await writeFile(resolve('artifacts/acceptance/independent-desktop-review/code-material-reproduction.json'),JSON.stringify(result,null,2));
  console.log(JSON.stringify(result,null,2));
} finally {await app.close();}
