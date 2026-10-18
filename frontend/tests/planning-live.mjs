// Opt-in real-model browser check; restricted to an empty, synthetic project.
import assert from 'node:assert/strict';
import { readFile, mkdir, writeFile } from 'node:fs/promises';
import { resolve, join } from 'node:path';
import { chromium } from 'playwright';

const url = process.env.RELAY_TEST_URL || 'http://127.0.0.1:5173';
const tokenPath = process.env.RELAY_ADMIN_TOKEN_FILE;
if (!tokenPath) throw new Error('Set RELAY_ADMIN_TOKEN_FILE to a local administrator token file.');
const token = (await readFile(tokenPath, 'utf8')).trim();
const artifacts = resolve(process.env.RELAY_ARTIFACTS_DIR || 'artifacts/planning-live');
await mkdir(artifacts, { recursive: true });
const headers = { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` };
const snapshot = async () => {
  const response = await fetch(url + '/api/tools/snapshot', { method: 'POST', headers, body: '{}' });
  assert.equal(response.status, 200);
  return response.json();
};
const before = await snapshot();
assert.equal(before.project.name, 'AI_PLANNING_SYNTHETIC_TEST', 'Real-model checks require the isolated synthetic test project.');
assert.equal(before.project.private_context, '');
assert.equal(before.tasks.length, 0, 'Do not send real task contexts to the model during this test.');
const browser = await chromium.launch({ headless: true,
  executablePath: process.env.RELAY_BROWSER_PATH || 'C:/Program Files/Google/Chrome/Application/chrome.exe' });
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  await page.goto(url);
  await page.getByLabel('访问令牌', { exact: true }).fill(token);
  await page.getByRole('button', { name: '进入工作空间' }).click();
  await page.getByRole('button', { name: 'AI 任务规划', exact: true }).click();
  await page.getByLabel('规划需求', { exact: true }).waitFor();
  await page.getByRole('button', { name: '新规划', exact: true }).waitFor({ state: 'visible' });
  await page.waitForFunction(() => !document.querySelector('[aria-label="选择规划记录"]')?.disabled);
  await page.screenshot({ path: join(artifacts, 'planning-empty.png'), fullPage: true });
  await page.getByLabel('规划需求', { exact: true }).fill('这是一次完全虚构的规划功能测试。开发一个活动签到小功能，只规划两项任务：签到接口、签到页面，页面依赖接口。两名同学，限时两小时，技术栈 FastAPI、React、SQLite。每个字段用一句短话，给出验收标准和交接提示词，不需要追问。仅生成草案。');
  console.log('Sending one real model planning request...');
  const responsePromise = page.waitForResponse(r => r.url().endsWith('/api/planning/chat') && r.request().method() === 'POST', { timeout: 200000 });
  await page.getByRole('button', { name: '发送', exact: true }).click();
  const response = await responsePromise;
  const payload = await response.json();
  if (response.status() !== 200) {
    await page.screenshot({ path: join(artifacts, 'planning-error.png'), fullPage: true });
    const error = { result: 'failed', http_status: response.status(), code: payload.error?.code, message: payload.error?.message };
    await writeFile(join(artifacts, 'planning-result.json'), JSON.stringify(error, null, 2));
    throw new Error(`Planning failed: HTTP ${error.http_status} ${error.code}: ${error.message}`);
  }
  assert.equal(payload.status, 'draft');
  assert(payload.plan.tasks.length > 0, 'Expected task suggestions');
  if (process.env.RELAY_TEST_CONTINUE_CHAT === '1') {
    await page.getByLabel('规划需求', { exact: true }).fill('保留这两项任务和依赖，只在第一项任务的验收标准中补充：需要验证重复签到。其余内容保持简短，不要增加新任务。');
    const revisedPromise = page.waitForResponse(r => r.url().endsWith('/api/planning/chat') && r.request().method() === 'POST', { timeout: 200000 });
    await page.getByRole('button', { name: '发送', exact: true }).click();
    const revised = await revisedPromise;
    const revisedPayload = await revised.json();
    if (revised.status() !== 200) throw new Error(`Continued chat failed: HTTP ${revised.status()} ${revisedPayload.error?.code}`);
    assert.equal(revisedPayload.draft_id, payload.draft_id);
    assert.equal(revisedPayload.version, payload.version + 1);
    assert.equal(revisedPayload.messages.length, 4);
  }
  const name = page.getByLabel('任务 1 名称', { exact: true });
  await name.waitFor();
  await page.screenshot({ path: join(artifacts, 'planning-draft.png'), fullPage: true });
  const changedName = (await name.inputValue()) + '（检查草案）';
  await name.fill(changedName);
  const savePromise = page.waitForResponse(r => r.url().endsWith(`/api/planning/drafts/${payload.draft_id}`) && r.request().method() === 'PUT');
  await page.getByRole('button', { name: '保存草案', exact: true }).click();
  assert.equal((await savePromise).status(), 200);
  await page.getByRole('button', { name: '确认创建任务', exact: true }).click();
  await page.getByRole('dialog', { name: '确认创建任务', exact: true }).waitFor();
  await page.getByRole('button', { name: '继续检查', exact: true }).click();
  // A refresh must restore the persisted conversation and manual edits.
  await page.reload();
  await page.getByRole('button', { name: 'AI 任务规划', exact: true }).click();
  await page.getByLabel('选择规划记录', { exact: true }).selectOption(payload.draft_id);
  await page.waitForFunction(expected => document.querySelector('[aria-label="任务 1 名称"]')?.value === expected, changedName);
  await page.screenshot({ path: join(artifacts, 'planning-restored.png'), fullPage: true });
  const after = await snapshot();
  assert.equal(after.tasks.length, before.tasks.length, 'Draft testing must not create formal tasks');
  const result = { result: 'passed', real_model_request: true, draft_id: payload.draft_id,
    suggested_tasks: payload.plan.tasks.length, manual_edit_and_restore: 'passed',
    confirmation_dialog: 'passed_without_confirming', formal_task_count_unchanged: true };
  if (process.env.RELAY_CONFIRM_SYNTHETIC_TASKS === '1') {
    const storedResponse = await fetch(url + `/api/planning/drafts/${payload.draft_id}`, { headers });
    const stored = await storedResponse.json();
    await page.getByRole('button', { name: '确认创建任务', exact: true }).click();
    const confirmPromise = page.waitForResponse(r => r.url().endsWith(`/drafts/${payload.draft_id}/confirm`) && r.request().method() === 'POST');
    await page.getByRole('button', { name: '创建这些任务', exact: true }).click();
    const confirmedResponse = await confirmPromise;
    assert.equal(confirmedResponse.status(), 200);
    const confirmed = await confirmedResponse.json();
    const retry = await fetch(url + `/api/planning/drafts/${payload.draft_id}/confirm`, {
      method: 'POST', headers, body: JSON.stringify({ expected_version: stored.version }),
    });
    assert.equal(retry.status, 200);
    assert.deepEqual(await retry.json(), confirmed);
    const final = await snapshot();
    assert.equal(final.tasks.length, stored.plan.tasks.length);
    for (const suggestion of stored.plan.tasks) {
      const id = confirmed.task_ids[suggestion.key];
      const task = final.tasks.find(t => t.task_id === id);
      assert(task);
      assert.equal(task.name, suggestion.name);
      assert.deepEqual(task.dependencies.slice().sort(), suggestion.dependencies.map(ref => confirmed.task_ids[ref] || ref).sort());
      assert.equal(final.contexts[id].data.next_steps, suggestion.handoff_prompt);
    }
    await page.getByRole('button', { name: '查看任务', exact: true }).click();
    await page.getByTestId('task-row').filter({ hasText: changedName }).waitFor();
    await page.reload();
    await page.getByTestId('task-row').filter({ hasText: changedName }).waitFor();
    await page.getByTestId('task-row').filter({ hasText: changedName }).click();
    await page.getByRole('tab', { name: '工作上下文', exact: true }).click();
    await page.getByText(stored.plan.tasks[0].handoff_prompt, { exact: true }).waitFor();
    await page.screenshot({ path: join(artifacts, 'planning-created.png'), fullPage: true });
    result.confirmation_dialog = 'confirmed_in_synthetic_database';
    result.formal_task_count_unchanged = false;
    result.confirmed_task_count = final.tasks.length;
    result.duplicate_confirmation = 'passed';
    result.task_context_and_dependencies = 'passed';
    result.refresh_after_creation = 'passed';
    result.continued_chat = process.env.RELAY_TEST_CONTINUE_CHAT === '1' ? 'passed' : 'not_requested';
  }
  await writeFile(join(artifacts, 'planning-result.json'), JSON.stringify(result, null, 2));
  console.log(JSON.stringify(result));
} finally { await browser.close(); }
