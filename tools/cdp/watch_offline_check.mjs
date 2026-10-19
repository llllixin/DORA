#!/usr/bin/env node
/**
 * 离线（未连后端）持续关注工作台回归：**未连后端时不得伪造可写操作**。
 *
 * 缘起：迭代 53 apply 期新增的 `/tmp/dora_watch_offline_check.mjs`（7/7 ALL PASS，见
 * `openspec/changes/archive/2026-09-13-fix-offline-join-action/tasks.md` 3.2）；原脚本在 `/tmp`
 * 已丢失 → 按归档记录逐条重建并落仓。
 *
 * 断言（7）：
 *   ① 页面如实标「离线演示」
 *   ② 在手委托行数与离线镜像一致（不静默空表）
 *   ③ 工具②「查看历史类似情况」禁用 + 显式原因「需连接后端」
 *   ④ 工具③「转为行动档案」禁用 + 显式原因（不是「点了没反应」）
 *   ⑤ 离线态不渲染「已升级 · 已移交」终态区（无升级数据时不伪造终态；在手 6 条全为 `watching`）
 *
 *      注：原记录的「离线写操作禁用」断言指向「恢复持续关注」按钮（`title="需连接后端"`），而该按钮只在
 *      `handedOff.length > 0` 的终态区渲染 —— 离线镜像无终态数据，元素本不存在，故换为上面这条等价强度的
 *      反伪造断言（同为「离线不得伪造可见能力」）。行级写操作（检查 / 暂停 / 删除）的离线诚实性**目前仍是
 *      缺口**（`apiSendStrict` 在 mock/网络失败时 `return fallback()` → toast 假成功），见
 *      `docs/持续优化路线.md` §2「持续关注行级写操作离线诚实性」。
 *   ⑥ 点击被禁用的工具③ → 不产生任何成功 toast（「已建档 / 已加入行动回路」）
 *   ⑦ 走向图如实标注（「离线镜像」或「暂无序列」，不画假线）
 *
 * 用法：node tools/cdp/watch_offline_check.mjs
 */
import {
  SEED_DATASOURCE, TOAST_OBSERVER, clickSelector, createSuite, ensureDemoHtml, evaluate, fatal, finish,
  goto, launchChrome, newPage, preparePage, screenshot, serveStatic, sleep, textOf, toastLog, visible,
} from './lib/cdp.mjs';
import path from 'node:path';

/** 离线镜像里在手的委托条数（`frontend/src/data.ts` 持续关注镜像；改动镜像时同步此常量并在结论里说明）。 */
const EXPECTED_IN_HAND = 6;

const suite = createSuite('watch_offline_check（单文件 demo · 离线）');
let chrome;
let server;

try {
  const html = await ensureDemoHtml();
  server = await serveStatic(path.dirname(html));
  chrome = await launchChrome();
  const { session } = await newPage(chrome.port);
  // demo 首开停在「数据入口」页（没有上传数据），用例自己预置数据源以便直接进页面
  await preparePage(session, { initScripts: [SEED_DATASOURCE, TOAST_OBSERVER] });
  await goto(session, `${server.url}/${path.basename(html)}#page=watch`, { waitSelector: '.whead' });

  // 本用例验证的是 **mock（无快照）产物**的离线语义；快照产物初始无委托且写操作在演示内生效 → 显式 SKIP
  if (await evaluate(session, '!!window.__DORA_DEMO_SNAPSHOT__')) {
    console.log('SKIP：当前产物是「快照 demo」（初始只有洞察、无任何委托）→ 本用例（mock 离线语义）未跑（不是通过）');
    console.log('  需要 mock 产物：移走 `frontend/design-demo/action-snapshot.json` 后 `npm run demo:html`');
    await finish(suite, [server?.close, chrome?.close]);
    process.exit(0);
  }

  // 深链直达时 `.whead` 是静态骨架（先于数据渲染）：必须等 `load()` 落定（mock 分支有 ~160ms 异步回退）
  // 再断言，否则读到的是初始态（0 行 / offline=false）。
  // 注意（2026-09-26 实测）：判据必须**限定在页面内** —— 新版外壳/侧栏也有一句「离线演示：当前为历史样例…」，
  // 用整页 `body.innerText` 会被它提前满足，于是又读到初始态（P030 同族：弱标记不算落定）。
  const loaded = await visible(session, `document.querySelector('.page.active .head')?.innerText.includes('离线演示') === true`, {
    timeout: 10000,
    label: '持续关注页头部出现「离线演示」（load 落定）',
  });
  if (!loaded) throw new Error('等待委托列表落定超时（持续关注页头部无「离线演示」标识）');

  const head = await textOf(session, '.page.active .head');
  suite.check('① 页面如实标「离线演示」', head.includes('离线演示'), `head="${head.replace(/\s+/g, ' / ')}"`);

  const rowCount = await evaluate(
    session,
    `[...document.querySelectorAll('.page.active .watch-table .wrow')].filter((r) => !r.textContent.includes('（暂无在手委托）')).length`,
  );
  suite.check('② 在手委托行 = 离线镜像条数', rowCount === EXPECTED_IN_HAND, `实际 ${rowCount} 行（期望 ${EXPECTED_IN_HAND}）`);

  // 打开工作台（选中第一条委托的标题区）
  const selected = await clickSelector(session, '.wrow .wtitle');
  const toolsReady = await visible(session, `document.querySelectorAll('.gwb-tool').length >= 3`, { timeout: 8000, label: '工作台三工具出现' });
  if (!toolsReady) throw new Error(`选中委托后工作台未渲染（clicked=${selected}）`);

  const tool2 = await evaluate(session, `(() => { const t = document.querySelectorAll('.gwb-tool')[1]; const b = t?.querySelector('button'); return { disabled: !!b?.disabled, note: (t?.querySelector('.gwb-note.warn')?.textContent ?? '').trim() }; })()`);
  suite.check('③ 工具② 检索禁用 + 显式原因', tool2.disabled && tool2.note.includes('需连接后端'), JSON.stringify(tool2));

  const tool3 = await evaluate(session, `(() => { const t = document.querySelectorAll('.gwb-tool')[2]; const b = t?.querySelector('button'); return { disabled: !!b?.disabled, note: (t?.querySelector('.gwb-note.warn')?.textContent ?? '').trim() }; })()`);
  suite.check('④ 工具③ 建档禁用 + 显式原因', tool3.disabled && tool3.note.includes('需连接后端'), JSON.stringify(tool3));

  const restore = await evaluate(session, `(() => { const z = document.querySelector('.handoff-zone'); return { rendered: !!z, head: document.body.innerText.includes('已升级 · 已移交') }; })()`);
  suite.check('⑤ 离线无终态数据时不渲染「已升级 · 已移交」区', !restore.rendered && !restore.head, JSON.stringify(restore));

  await evaluate(session, `document.querySelectorAll('.gwb-tool')[2].querySelector('button').click()`);
  await sleep(700);
  const log = await toastLog(session);
  const fakeSuccess = log.filter((t) => t.includes('已建档') || t.includes('已加入行动回路'));
  suite.check('⑥ 点击被禁用的建档按钮 → 无成功 toast', fakeSuccess.length === 0, `toast 历史=${JSON.stringify(log)}`);

  const tool1 = await evaluate(session, `(() => { const t = document.querySelectorAll('.gwb-tool')[0]; return { hasSpark: !!t?.querySelector('.gwb-spark'), note: (t?.querySelector('.gwb-note')?.textContent ?? '').trim() }; })()`);
  suite.check('⑦ 走向图如实标注（离线镜像 / 暂无序列）', !tool1.hasSpark ? tool1.note.includes('暂无序列') : tool1.note.includes('离线镜像'), JSON.stringify(tool1));

  await screenshot(session, 'watch-offline');
} catch (err) {
  fatal(err);
}

await finish(suite, [server?.close, chrome?.close]);
