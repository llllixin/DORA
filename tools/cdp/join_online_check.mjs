#!/usr/bin/env node
/**
 * 在线（后端 + Vite dev 代理）「加入行动回路」回归：认领 = **服务端归属**，不靠本机集合。
 *
 * 缘起：迭代 53 的 `/tmp/dora_live_join_check.mjs`（9/9 ALL PASS，见
 * `openspec/changes/archive/2026-09-13-fix-offline-join-action/tasks.md` 4.3）；原脚本在 `/tmp`
 * 已丢失 → 按归档记录逐条重建并落仓。
 *
 * 前置：① `docker compose up -d postgres` ② `cd backend && uvicorn app.main:app --port 8000`
 *      ③ `cd frontend && npm install`（Vite dev 的 `/api` 代理要用）。
 * 后端不在线时本用例 **SKIP（退出码 0）并打印原因** —— 显式记录「未跑」，不当成通过。
 *
 * 断言（9）：
 *   ① `GET /api/health` → `status=ok`
 *   ② 页面确已进入在线态（真实引擎图表出现）
 *   ③ 洞察页按钮文案 =「加入行动回路 →」
 *   ④ 点击命中 → 路由跳 `#page=action`
 *   ⑤ 行动回路「我的档案 N 份」且 N ≥ 1（服务端归属，而非本机集合）
 *   ⑥ 可见档案编号 `PRF-0831`
 *   ⑦ 无「还没有行动档案」空态、无「离线演示」标识
 *   ⑧ toast 历史含在线成功文案，且**不含**「未连接后端」（在线不得走离线分支）
 *   ⑨ 契约核对：`GET /api/action/cases?origin=mine` 认领**幂等** —— 点击后含且**仅含 1 条** `PRF-0831`
 *
 * ⑨ 的基线约定（2026-09-17 在线首跑修正，P024「门禁要自持基线」）：**不预设**「点击前就已认领」。
 *   出厂 seed 后 5 条档案 `origin` 全是 `demo`（`mine` 为空）→ 首次点击把它认领为 `mine` 是**正确行为**；
 *   原断言要求「点击前就含」只有在自己把库改过之后第二次跑才会绿（依赖上一次运行留下的状态），
 *   故改为断言「点击后数量恰为 1 且不减少」—— 无论基线是 `demo` 还是已认领都成立，且仍能抓住「重复点击翻倍」。
 *
 * 用法：node tools/cdp/join_online_check.mjs
 */
import {
  SEED_DATASOURCE, TOAST_OBSERVER, apiJson, backendUp, bodyText, clickByText, createSuite, evaluate,
  fatal, finish, goto, hashOf, launchChrome, newPage, preparePage, screenshot, startViteDev, textOf,
  toastLog, visible,
} from './lib/cdp.mjs';

const INSIGHT_URL = '/#page=insight&type=problem&idx=0';
const CASE_CODE = 'PRF-0831';
const suite = createSuite('join_online_check（后端在线 · Vite dev 代理）');

/** `origin=mine` 列表里出现 `code` 的条数（认领幂等判据：同一洞察只应有一条档案）。 */
function countCode(payload, code) {
  const list = Array.isArray(payload?.cases) ? payload.cases : [];
  return list.filter((c) => c.code === code).length;
}

if (!(await backendUp())) {
  console.log('SKIP：后端未在线（http://127.0.0.1:8000/api/health 不可达）→ 本用例未跑（不是通过）');
  console.log('  启动：docker compose up -d postgres && cd backend && uvicorn app.main:app --port 8000');
  process.exit(0);
}

let chrome;
let vite;

try {
  const health = await apiJson('/health');
  suite.check('① 后端健康检查', health?.status === 'ok', JSON.stringify(health));

  const mineBefore = countCode(await apiJson('/action/cases?origin=mine'), CASE_CODE);

  vite = await startViteDev();
  chrome = await launchChrome();
  const { session } = await newPage(chrome.port);
  await preparePage(session, { initScripts: [SEED_DATASOURCE, TOAST_OBSERVER] });
  await goto(session, `${vite.url}${INSIGHT_URL}`, { waitSelector: '.main-buttons button', timeout: 20000 });

  const synced = await visible(session, `!!document.querySelector('[data-chart-source=engine]')`, {
    timeout: 15000,
    label: '真实引擎图表出现',
  });
  suite.check('② 页面进入在线态（引擎图表可见）', synced, `toast 历史=${JSON.stringify(await toastLog(session))}`);

  const label = await textOf(session, '.main-buttons button');
  suite.check('③ 洞察页按钮文案 =「加入行动回路 →」', label === '加入行动回路 →', `实际「${label}」`);

  const clicked = await clickByText(session, '.main-buttons button', '加入行动回路');
  const routed = await visible(session, `location.hash === '#page=action'`, { timeout: 8000, label: '路由跳到 #page=action' });
  suite.check('④ 点击命中 → 路由跳行动回路', clicked && routed, `clicked=${clicked} hash=${await hashOf(session)}`);

  // 页面骨架会先显示「我的档案 0 份」；等待服务端列表落定，而不是把骨架当最终状态。
  const counted = await visible(session, `/我的档案 [1-9]\\d* 份/.test(document.body.innerText)`, { timeout: 10000, label: '行动回路出现至少 1 份我的档案' });
  const body = await bodyText(session);
  const mineCount = Number(body.match(/我的档案 (\d+) 份/)?.[1] ?? '0');
  suite.check('⑤ 「我的档案」计数 ≥ 1（服务端归属）', counted && mineCount >= 1, `我的档案 ${mineCount} 份`);

  suite.check('⑥ 可见档案编号 ' + CASE_CODE, body.includes(CASE_CODE), `body 是否含编号：${body.includes(CASE_CODE)}`);

  suite.check(
    '⑦ 无空态、无「离线演示」标识',
    !body.includes('还没有行动档案') && !body.includes('离线演示'),
    `空态=${body.includes('还没有行动档案')} 离线标识=${body.includes('离线演示')}`,
  );

  const log = await toastLog(session);
  const okToast = log.some((t) => t.includes('已加入行动回路'));
  const offlineLeak = log.some((t) => t.includes('未连接后端'));
  suite.check('⑧ 在线成功文案出现且未走离线分支', okToast && !offlineLeak, `toast 历史=${JSON.stringify(log)}`);

  const mineAfter = countCode(await apiJson('/action/cases?origin=mine'), CASE_CODE);
  suite.check(
    `⑨ 认领幂等：origin=mine 含且仅含 1 条 ${CASE_CODE}`,
    mineAfter === 1 && mineAfter >= mineBefore,
    `点击前 ${mineBefore} 条 → 点击后 ${mineAfter} 条（基线不预设：出厂 seed=demo 时为 0，已认领时为 1）`,
  );

  await screenshot(session, 'join-online');
} catch (err) {
  fatal(err);
}

await finish(suite, [vite?.close, chrome?.close]);
