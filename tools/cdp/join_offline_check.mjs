#!/usr/bin/env node
/**
 * 离线（未连后端）「加入行动回路」真点击回归。
 *
 * 缘起：2026-09-13 用户实测「洞察点『加入行动回路』→ 行动回路是空态」；修复前 4 FAIL / 6
 * （首次落库见 `openspec/changes/archive/2026-09-13-fix-offline-join-action/tasks.md` 4.1）。
 * 原脚本写在 `/tmp`，随系统清理已丢失 → 按归档记录逐条重建并落仓（`tools/cdp/`）。
 *
 * 断言（6）：
 *   ① 洞察页按钮文案 =「加入行动回路 →」（证明点的是正确元素）
 *   ② 点击命中 → 路由跳到 `#page=action`
 *   ③ 本机加入集合含 `p1`（离线不丢意图）
 *   ④ 行动回路可见档案 `PRF-0831`（声称已加入 ⇒ 必须可见）
 *   ⑤ 无「还没有行动档案」空态
 *   ⑥ toast 与可见性一致，且是离线诚实文案（含「未连接后端」）
 *
 * 用法：node tools/cdp/join_offline_check.mjs
 */
import {
  SEED_DATASOURCE, TOAST_OBSERVER, bodyText, clickByText, createSuite, ensureDemoHtml, evaluate, fatal,
  finish, goto, hashOf, launchChrome, newPage, preparePage, screenshot, serveStatic, textOf, toastLog, visible,
} from './lib/cdp.mjs';
import path from 'node:path';

const INSIGHT_URL = '#page=insight&type=problem&idx=0';
const suite = createSuite('join_offline_check（单文件 demo · 离线）');
let chrome;
let server;

try {
  const html = await ensureDemoHtml();
  server = await serveStatic(path.dirname(html));
  chrome = await launchChrome();
  const { session } = await newPage(chrome.port);
  // demo 首开停在「数据入口」页（没有上传数据），用例自己预置数据源以便直接进页面
  await preparePage(session, { initScripts: [SEED_DATASOURCE, TOAST_OBSERVER] });
  await goto(session, `${server.url}/${path.basename(html)}${INSIGHT_URL}`, { waitSelector: '.main-buttons button' });

  // 本用例验证的是 **mock（无快照）产物**的离线语义；快照产物的写操作在演示内生效 → 显式 SKIP
  if (await evaluate(session, '!!window.__DORA_DEMO_SNAPSHOT__')) {
    console.log('SKIP：当前产物是「快照 demo」（洞察 / 档案 / 关注来自构建期快照，写操作在演示内生效）→ 本用例（mock 离线语义）未跑（不是通过）');
    console.log('  需要 mock 产物：移走 `frontend/design-demo/action-snapshot.json` 后 `npm run demo:html`');
    await finish(suite, [server?.close, chrome?.close]);
    process.exit(0);
  }

  const joinedBefore = await evaluate(session, `localStorage.getItem('doraJoinedAction') ?? '[]'`);
  if (joinedBefore !== '[]' && joinedBefore !== '') {
    console.log(`· 提示：本次页面不是干净基线（doraJoinedAction=${joinedBefore}），断言③只判「含 p1」`);
  }

  const label = await textOf(session, '.main-buttons button');
  suite.check('① 洞察页按钮文案 =「加入行动回路 →」', label === '加入行动回路 →', `实际「${label}」`);

  const clicked = await clickByText(session, '.main-buttons button', '加入行动回路');
  const routed = await visible(session, `location.hash === '#page=action'`, { timeout: 8000, label: '路由跳到 #page=action' });
  suite.check('② 点击命中 → 路由跳行动回路', clicked && routed, `clicked=${clicked} hash=${await hashOf(session)} 点前本机集合=${joinedBefore}`);

  const joined = await evaluate(session, `JSON.parse(localStorage.getItem('doraJoinedAction') ?? '[]')`);
  suite.check('③ 本机加入集合含 p1（离线不丢意图）', Array.isArray(joined) && joined.includes('p1'), `doraJoinedAction=${JSON.stringify(joined)}`);

  const seen = await visible(session, `document.body.innerText.includes('PRF-0831')`, { timeout: 8000, label: '行动回路出现档案 PRF-0831' });
  suite.check('④ 行动回路可见档案 PRF-0831', seen);

  const body = await bodyText(session);
  suite.check('⑤ 无「还没有行动档案」空态', !body.includes('还没有行动档案'), body.includes('还没有行动档案') ? '仍见空态文案' : '未见空态');

  const log = await toastLog(session);
  const last = Array.isArray(log) ? log.at(-1) ?? '' : '';
  suite.check(
    '⑥ toast 与可见性一致 + 离线诚实文案',
    last.includes('已加入行动回路') && last.includes('未连接后端') && seen,
    `toast 历史=${JSON.stringify(log)}`,
  );

  await screenshot(session, 'join-offline');
} catch (err) {
  fatal(err);
}

await finish(suite, [server?.close, chrome?.close]);
