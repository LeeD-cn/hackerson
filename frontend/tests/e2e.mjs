// Real browser -> Vite proxy -> real backend -> isolated SQLite database.
// No mocked API responses, no changes to the user's running services or data.
import assert from 'node:assert/strict';
import { randomBytes } from 'node:crypto';
import { spawn } from 'node:child_process';
import { createWriteStream, existsSync } from 'node:fs';
import { mkdir, mkdtemp, readFile } from 'node:fs/promises';
import { createServer } from 'node:net';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { setTimeout as delay } from 'node:timers/promises';
import { chromium } from 'playwright';

const frontend = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const root = resolve(frontend, '..');
// Backend stays in its own clean checkout; never import uncommitted P1 drafts.
const backendRoot = resolve(process.env.RELAY_BACKEND_ROOT || root);
const checkBE02 = process.env.RELAY_BE02 === '1';
const python = process.env.RELAY_PYTHON || join(root, '.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python');
const browserPath = process.env.RELAY_BROWSER_PATH || (process.platform === 'win32' ? 'C:/Program Files/Google/Chrome/Application/chrome.exe' : undefined);
const token = randomBytes(32).toString('hex');
const tempRoot = join(frontend, '.tmp');
const artifacts = join(frontend, 'artifacts');
await mkdir(tempRoot, { recursive: true });
await mkdir(artifacts, { recursive: true });
const temp = await mkdtemp(join(tempRoot, 'e2e-'));
const children = new Set();
const logs = [];
let browser;
let stopping = false;

async function freePort() {
  const server = createServer();
  await new Promise((yes, no) => { server.once('error', no); server.listen(0, '127.0.0.1', yes); });
  const port = server.address().port;
  await new Promise(yes => server.close(yes));
  return port;
}

function launch(command, args, cwd, env, name) {
  const log = createWriteStream(join(temp, `${name}.log`), { flags: 'a' });
  logs.push(log);
  const child = spawn(command, args, { cwd, env: { ...process.env, ...env }, windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'] });
  child.stdout.pipe(log, { end: false }); child.stderr.pipe(log, { end: false });
  child.on('error', error => { child.launchError = error; });
  children.add(child);
  return child;
}

async function stop(child) {
  if (!child || child.exitCode !== null || child.signalCode !== null) return;
  const closed = new Promise(yes => child.once('exit', yes));
  child.kill();
  await Promise.race([closed, delay(4000)]);
  if (child.exitCode === null && child.signalCode === null) { child.kill('SIGKILL'); await Promise.race([closed, delay(2000)]); }
}

async function ready(url, child) {
  const deadline = Date.now() + 20000;
  while (Date.now() < deadline) {
    if (child.launchError) throw child.launchError;
    if (child.exitCode !== null) throw new Error(`Service stopped before ready: ${url}. Logs: ${temp}`);
    try { const response = await fetch(url, { signal: AbortSignal.timeout(700) }); if (response.ok) return; } catch { /* Wait within bounded deadline. */ }
    await delay(150);
  }
  throw new Error(`Service not ready: ${url}. Logs: ${temp}`);
}

async function cleanup() {
  if (stopping) return;
  stopping = true;
  await browser?.close().catch(() => {});
  await Promise.all([...children].map(stop));
  logs.forEach(log => log.end());
}
for (const signal of ['SIGINT', 'SIGTERM']) process.once(signal, async () => { await cleanup(); process.exit(130); });

try {
  assert(existsSync(python), 'Set RELAY_PYTHON to the project virtual-environment Python executable.');
  const backendPort = await freePort();
  let frontPort = await freePort();
  while (frontPort === backendPort) frontPort = await freePort();
  const backendUrl = `http://127.0.0.1:${backendPort}`;
  const frontendUrl = `http://127.0.0.1:${frontPort}`;
  const startBackend = () => launch(python, ['-m', 'backend', '--port', String(backendPort), '--db', join(temp, 'relay.db')], backendRoot,
    { RELAY_ADMIN_TOKEN: token, PYTHONUTF8: '1' }, 'backend');
  let backend = startBackend();
  await ready(`${backendUrl}/health`, backend);
  const vite = launch(process.execPath, [join(frontend, 'node_modules/vite/bin/vite.js'), '--host', '127.0.0.1', '--port', String(frontPort)], frontend,
    { RELAY_API_URL: backendUrl }, 'vite');
  await ready(frontendUrl, vite);

  async function api(action, body = {}, credential = token) {
    const response = await fetch(`${backendUrl}/api/tools/${action}`, { method: 'POST', headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${credential}` }, body: JSON.stringify(body), signal: AbortSignal.timeout(5000) });
    const result = await response.json();
    assert(response.ok, `${action} failed: ${result.error?.code}`);
    return result;
  }

  browser = await chromium.launch({ headless: true, ...(browserPath ? { executablePath: browserPath } : {}) });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1050 } });
  page.setDefaultTimeout(10000);
  const pageErrors = [];
  const requests = [];
  page.on('request', request => requests.push(new URL(request.url()).pathname));
  page.on('pageerror', error => pageErrors.push(error.message));
  await page.goto(frontendUrl);
  await page.getByLabel('访问令牌').fill('invalid-token');
  await page.getByRole('button', { name: '进入工作空间' }).click();
  await page.getByRole('alert').waitFor();
  await page.getByLabel('访问令牌').fill(token);
  await page.getByRole('button', { name: '进入工作空间' }).click();
  await page.getByRole('heading', { name: '从第一项任务开始' }).waitFor();
  assert(requests.indexOf('/health') >= 0 && requests.indexOf('/health') < requests.indexOf('/api/tools/snapshot'), 'Health check must precede snapshot');
  console.log('PASS: real authentication, rejected invalid token, empty workspace');

  async function createTask(name, goal, dependency) {
    await page.getByRole('button', { name: '新建任务', exact: true }).click();
    const dialog = page.getByRole('dialog', { name: '创建新任务' });
    await dialog.getByLabel('任务名称').fill(name);
    await dialog.getByLabel('任务目标').fill(goal);
    await dialog.getByLabel('执行者', { exact: true }).fill('前端联调成员');
    await dialog.getByLabel('Git 分支').fill('feature/web-console');
    await dialog.getByLabel('验收标准').fill('创建与编辑后刷新仍保留数据。');
    if (dependency) await dialog.getByLabel(dependency, { exact: true }).check();
    await dialog.getByText('详细描述、接口契约与技术约束', { exact: true }).click();
    await dialog.getByLabel('公开接口契约').fill('POST /registrations: {name} -> {registration_id}');
    await dialog.getByLabel('技术约束').fill('字段使用 snake_case。');
    await dialog.getByRole('button', { name: '创建任务', exact: true }).click();
    await dialog.waitFor({ state: 'hidden' });
    await page.getByRole('heading', { name, exact: true }).first().waitFor();
  }
  await createTask('报名接口 · 联调', '提供活动报名接口。');
  await createTask('报名表单 · 联调', '提交报名并显示结果。', '报名接口 · 联调');
  let snapshot = await api('snapshot');
  assert.equal(snapshot.tasks.length, 2);
  const apiTask = snapshot.tasks.find(t => t.name === '报名接口 · 联调');
  const formTask = snapshot.tasks.find(t => t.name === '报名表单 · 联调');
  assert.deepEqual(formTask.dependencies, [apiTask.task_id]);
  assert.equal(snapshot.notifications.length, 2);
  console.log('PASS: UI creates two persisted tasks with real dependency and notification records');

  await page.getByRole('button', { name: '编辑任务', exact: true }).click();
  let edit = page.getByRole('dialog', { name: '编辑任务' });
  await edit.getByLabel('任务目标').fill('提交报名、校验学号并显示结果。');
  await edit.getByLabel('修改理由').fill('按联调结果补充学号校验。');
  await edit.getByRole('button', { name: '保存修改' }).click();
  await edit.waitFor({ state: 'hidden' });
  await page.reload();
  await page.getByRole('heading', { name: '报名表单 · 联调', exact: true }).first().waitFor();
  assert.equal(await page.getByTestId('task-row').count(), 2);
  assert.match(await page.getByLabel('任务详情').innerText(), /提交报名、校验学号并显示结果。/);
  snapshot = await api('snapshot');
  assert.equal(snapshot.tasks.find(t => t.task_id === formTask.task_id).version, 2);
  console.log('PASS: edit sends expected_version and page reload preserves persisted data');

  // Concurrent external change must not be overwritten by an old form.
  await page.getByRole('button', { name: '编辑任务', exact: true }).click();
  edit = page.getByRole('dialog', { name: '编辑任务' });
  await edit.getByLabel('任务目标').fill('不应覆盖新版本的草稿');
  await edit.getByLabel('修改理由').fill('并发验证');
  await api('edit_task', { task_id: formTask.task_id, expected_version: 2, patch: { goal: '另一个会话已更新目标。' }, reason: '并发修改' });
  await edit.getByRole('button', { name: '保存修改' }).click();
  await edit.getByRole('alert').waitFor();
  assert.equal(await edit.getByLabel('任务目标').inputValue(), '不应覆盖新版本的草稿');
  assert.equal((await api('snapshot')).tasks.find(t => t.task_id === formTask.task_id).goal, '另一个会话已更新目标。');
  page.once('dialog', dialog => dialog.accept());
  await edit.getByRole('button', { name: '载入最新版本并替换草稿' }).click();
  await edit.getByText('已载入最新版本，请重新核对并编辑。').waitFor();
  assert.equal(await edit.getByLabel('任务目标').inputValue(), '另一个会话已更新目标。');
  await edit.getByLabel('任务目标').fill('提交报名、校验学号并显示结果。');
  await edit.getByRole('button', { name: '保存修改' }).click();
  await edit.waitFor({ state: 'hidden' });
  console.log('PASS: real 409 preserves draft; explicit reload uses the new version');

  // Server remains the authority for DAG validation.
  await page.getByTestId('task-row').filter({ hasText: '报名接口 · 联调' }).click();
  await page.getByRole('button', { name: '编辑任务', exact: true }).click();
  edit = page.getByRole('dialog', { name: '编辑任务' });
  await edit.getByLabel('报名表单 · 联调', { exact: true }).check();
  await edit.getByLabel('修改理由').fill('验证循环依赖被拒绝');
  await edit.getByRole('button', { name: '保存修改' }).click();
  await edit.getByRole('alert').waitFor();
  assert.deepEqual((await api('snapshot')).tasks.find(t => t.task_id === apiTask.task_id).dependencies, []);
  page.once('dialog', dialog => dialog.accept());
  await edit.getByRole('button', { name: '取消', exact: true }).click();
  await edit.waitFor({ state: 'hidden' });
  console.log('PASS: real 422 shown, rejected dependency cycle leaves database unchanged');

  // TaskPatch has distinct null semantics: only parent_id is cleared with null.
  await page.getByTestId('task-row').filter({ hasText: '报名表单 · 联调' }).click();
  for (const parent of [apiTask.task_id, '']) {
    await page.getByRole('button', { name: '编辑任务', exact: true }).click();
    edit = page.getByRole('dialog', { name: '编辑任务' });
    await edit.getByLabel(/^父任务/).selectOption(parent);
    await edit.getByLabel('修改理由').fill(parent ? '组织子任务层级' : '移除父任务');
    await edit.getByRole('button', { name: '保存修改' }).click();
    await edit.waitFor({ state: 'hidden' });
    const updated = (await api('snapshot')).tasks.find(t => t.task_id === formTask.task_id);
    assert.equal(updated.parent_id, parent || null);
    assert.deepEqual(updated.dependencies, [apiTask.task_id]);
    assert.equal(updated.goal, '提交报名、校验学号并显示结果。');
  }
  console.log('PASS: TaskPatch clears parent_id with null while omitted fields and dependencies stay unchanged');

  await page.getByLabel('搜索任务').fill('不存在的任务');
  await page.getByRole('heading', { name: '没有匹配的任务' }).waitFor();
  await page.getByRole('button', { name: '清除筛选' }).click();
  await page.getByLabel('筛选任务状态').selectOption('done');
  await page.getByRole('heading', { name: '没有匹配的任务' }).waitFor();
  await page.getByLabel('筛选任务状态').selectOption('all');

  // Confirm notification states come from the task agent, not page controls.
  const credential = await api('issue_task_token', { task_id: formTask.task_id });
  const ownNotices = await api('get_notifications', {}, credential.token);
  await api('acknowledge_change', { notification_id: ownNotices.notifications[0].id, status: 'acknowledged', note: '已理解本次修改' }, credential.token);
  await page.getByRole('button', { name: '刷新数据' }).click();
  await page.getByRole('button', { name: /变更通知/ }).click();
  await page.getByLabel('筛选通知状态').selectOption('acknowledged');
  await page.getByText('已确认理解', { exact: true }).last().waitFor();
  assert((await api('snapshot')).tasks.every(t => t.status === 'todo'));
  await page.getByRole('button', { name: /任务空间/ }).click();
  await page.screenshot({ path: join(artifacts, 'desktop.png'), fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({ path: join(artifacts, 'mobile.png'), fullPage: true });
  assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), 'Mobile layout overflows horizontally');
  await page.getByRole('button', { name: '新建任务', exact: true }).click();
  const mobileDialog = page.getByRole('dialog', { name: '创建新任务' });
  assert(await mobileDialog.getByLabel('任务名称').evaluate(node => document.activeElement === node), 'Task name should receive initial modal focus');
  await mobileDialog.getByLabel('任务名称').fill('   ');
  await mobileDialog.getByLabel('任务目标').fill('测试空白名称');
  await mobileDialog.getByRole('button', { name: '创建任务', exact: true }).click();
  await mobileDialog.getByRole('alert').waitFor();
  assert.equal((await api('snapshot')).tasks.length, 2);
  await page.screenshot({ path: join(artifacts, 'mobile-editor.png') });
  page.once('dialog', dialog => dialog.accept());
  await page.keyboard.press('Escape');
  await mobileDialog.waitFor({ state: 'hidden' });
  await page.setViewportSize({ width: 1440, height: 1050 });
  console.log('PASS: search, filters, distinct notification state, mobile form validation and keyboard dismissal');

  await stop(backend);
  await page.getByRole('button', { name: '刷新数据' }).click();
  await page.getByRole('alert').waitFor();
  await page.getByText('同步失败 · 显示上次数据', { exact: true }).waitFor();
  assert.equal(await page.getByTestId('task-row').count(), 2);
  backend = startBackend();
  await ready(`${backendUrl}/health`, backend);
  await page.reload();
  await page.getByTestId('task-row').first().waitFor();
  assert.equal(await page.getByTestId('task-row').count(), 2);
  assert.equal((await api('snapshot')).tasks.find(t => t.task_id === formTask.task_id).goal, '提交报名、校验学号并显示结果。');
  console.log('PASS: backend restart reuses SQLite; browser reload restores the saved tasks');

  if (checkBE02) {
    assert(existsSync(join(backendRoot, 'backend/be02.py')), 'RELAY_BE02 requires a backend checkout containing backend.be02');
    const fixture = join(backendRoot, '.local/be02', `frontend-${randomBytes(6).toString('hex')}.json`);
    async function runFixture(command) {
      const child = launch(python, ['-m', 'backend.be02', command, '--url', backendUrl, '--credentials', fixture], backendRoot,
        { RELAY_ADMIN_TOKEN: token, PYTHONUTF8: '1' }, `be02-${command}`);
      await new Promise((yes, no) => {
        const timer = setTimeout(() => { child.kill(); no(new Error(`BE-02 ${command} timed out; inspect local logs`)); }, 30000);
        child.once('error', error => { clearTimeout(timer); no(error); });
        child.once('exit', code => { clearTimeout(timer); code === 0 ? yes() : no(new Error(`BE-02 ${command} failed; inspect local logs`)); });
      });
    }
    await runFixture('seed');
    await runFixture('check');
    const bundle = JSON.parse(await readFile(fixture, 'utf8'));
    await page.getByRole('button', { name: '刷新数据' }).click();
    await page.getByTestId('task-row').filter({ hasText: 'BE02-A-' }).click();
    await page.getByRole('tab', { name: '工作上下文' }).click();
    const panel = page.getByRole('tabpanel');
    await panel.getByText(bundle.tasks.a.private_marker, { exact: true }).waitFor();
    assert(!(await panel.innerText()).includes(bundle.tasks.b.private_marker));
    assert.equal(await panel.locator('section').filter({ has: page.getByRole('heading', { name: '待办事项', exact: true }) }).locator('p').innerText(), '尚未填写');
    const beforeRestart = (await api('snapshot')).contexts[bundle.tasks.a.task_id];
    assert.equal(beforeRestart.version, bundle.tasks.a.expected_context.version);
    await stop(backend);
    backend = startBackend();
    await ready(`${backendUrl}/health`, backend);
    await runFixture('verify-restored');
    await page.reload();
    await page.getByRole('tab', { name: '工作上下文' }).click();
    await page.getByRole('tabpanel').getByText(bundle.tasks.a.private_marker, { exact: true }).waitFor();
    // Task credentials are not accepted as control-plane credentials.
    await page.getByRole('button', { name: '退出登录' }).click();
    await page.getByLabel('访问令牌').fill(bundle.tasks.a.token);
    await page.getByRole('button', { name: '进入工作空间' }).click();
    await page.getByRole('alert').filter({ hasText: '当前令牌不能查看控制台' }).waitFor();
    assert.equal(await page.getByTestId('task-row').count(), 0);
    await page.getByLabel('访问令牌').fill(token);
    await page.getByRole('button', { name: '进入工作空间' }).click();
    await page.getByTestId('task-row').first().waitFor();
    console.log('PASS: BE-02 seed/check, null/empty context display, task-token rejection and restart restoration');
  }

  // A master role may inspect the UI but cannot see edit/create controls.
  const reviewer = await api('issue_role_token', { role: 'reviewer' });
  await page.getByRole('button', { name: '退出登录' }).click();
  await page.getByLabel('访问令牌').fill(reviewer.token);
  await page.getByRole('button', { name: '进入工作空间' }).click();
  await page.getByTestId('task-row').first().waitFor();
  assert.equal(await page.getByRole('button', { name: '新建任务', exact: true }).count(), 0);
  assert.equal(await page.getByRole('button', { name: '编辑任务', exact: true }).count(), 0);
  await page.getByRole('button', { name: '退出登录' }).click();
  assert.equal(await page.evaluate(() => sessionStorage.getItem('relay.console.token')), null);
  await page.reload();
  await page.getByRole('heading', { name: '连接项目空间' }).waitFor();
  assert.deepEqual(pageErrors, []);
  console.log('PASS: reviewer read-only UI; logout clears token; no browser runtime errors');
  console.log(`Screenshots: ${artifacts}`);
  console.log('All frontend integration checks passed. Test services will be stopped.');
} catch (error) {
  console.error(`Frontend integration failed. Logs: ${temp}`);
  throw error;
} finally {
  await cleanup();
}
