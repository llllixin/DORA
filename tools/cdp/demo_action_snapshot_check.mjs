#!/usr/bin/env node
/**
 * 快照 demo 的「洞察 → 升级 → 行动」链路回归（change `demo-real-action-snapshot` + 2026-09-26 编号统一/初始态收敛）。
 *
 * 前提：demo 由 `DORA_DEMO_API=<后端> npm run demo:html` 生成（内含 `window.__DORA_DEMO_SNAPSHOT__`）。
 * 产物无快照时本用例 **SKIP**（打印原因、退出码 0），不当成通过。
 *
 * 断言（7）：
 *   ① 只读标注存在（「真实数据快照 · <时间> · 非实时后端」）
 *   ② 初始**没有行动**：行动回路「我的档案 0 份」
 *   ③ 初始**没有关注**：持续关注「0 个业务目标持续关注中」
 *   ④ 洞察带统一**案号**（洞察详情 tag 含 `PRF-0831`）
 *   ⑤ 升级该洞察（「加入行动回路 →」）后行动回路出现 `PRF-0831`（我的档案 1 份）
 *   ⑥ 该档案详情渲染步骤与负责专家；且编号与洞察一致（档案 code = 洞察 tag 里的案号）
 *   ⑦ 演示内推进生效（点「开始」→ toast + 待办少一个）；未覆盖的写操作（上传 / 委托检查）仍如实 409
 *
 * 用法：node tools/cdp/demo_action_snapshot_check.mjs
 */
import {
  SEED_DATASOURCE, TOAST_OBSERVER, bodyText, clickByText, createSuite, ensureDemoHtml, evaluate, fatal,
  finish, goto, launchChrome, newPage, preparePage, screenshot, serveStatic, sleep, textOf, toastLog, visible,
} from './lib/cdp.mjs';
import path from 'node:path';

const CASE_NO = 'PRF-0831';
const suite = createSuite('demo_action_snapshot_check（快照 demo：只有洞察 → 升级才有行动，同编号）');
let chrome;
let server;

const url = (html, hash = '') => `${server.url}/${path.basename(html)}${hash}`;

try {
  const html = await ensureDemoHtml();
  server = await serveStatic(path.dirname(html));
  chrome = await launchChrome();
  const { session } = await newPage(chrome.port);
  await preparePage(session, { initScripts: [SEED_DATASOURCE, TOAST_OBSERVER] });

  await goto(session, url(html, '#page=action'), { waitSelector: '.page.active' });
  if (!(await evaluate(session, '!!window.__DORA_DEMO_SNAPSHOT__'))) {
    console.log('SKIP：当前产物不含真实数据快照（`window.__DORA_DEMO_SNAPSHOT__` 未注入）→ 本用例未跑（不是通过）');
    console.log('  生成方式：DORA_DEMO_API=http://127.0.0.1:8010/api npm run demo:html（需后端在线）');
    await finish(suite, [server?.close, chrome?.close]);
    process.exit(0);
  }

  const badgeText = await evaluate(session, `document.querySelector('.demo-snapshot-badge')?.textContent ?? ''`);
  suite.check('① 只读标注含「真实数据快照」与时间', /真实数据快照 · .+ · 非实时后端/.test(badgeText), `标注="${badgeText}"`);

  const actionEmpty = await visible(session, `document.body.innerText.includes('我的档案 0 份')`, { timeout: 10000, label: '行动回路初始为空' });
  suite.check('② 初始没有行动（我的档案 0 份）', actionEmpty, `含「我的档案 0 份」=${actionEmpty}`);

  await goto(session, url(html, '#page=watch'), { waitSelector: '.page.active' });
  const watchEmpty = await visible(session, `document.body.innerText.includes('0 个业务目标持续关注中')`, { timeout: 10000, label: '持续关注初始为空' });
  suite.check('③ 初始没有关注（0 个业务目标持续关注中）', watchEmpty, `含「0 个业务目标持续关注中」=${watchEmpty}`);

  await goto(session, url(html, '#page=insight&type=problem&idx=0'), { waitSelector: '.detail-top' });
  const insightTag = await textOf(session, '.detail-top .tag');
  suite.check('④ 洞察带统一案号', insightTag.includes(CASE_NO), `洞察 tag="${insightTag}"`);

  await clickByText(session, '.main-buttons button', '加入行动回路');
  await sleep(1200);
  await goto(session, url(html, '#page=action'), { waitSelector: '.page.active' });
  const escalated = await visible(session, `document.body.innerText.includes('我的档案 1 份')`, { timeout: 10000, label: '升级后出现 1 份档案' });
  const actionBody = await bodyText(session);
  suite.check('⑤ 升级后行动回路出现该档案（我的档案 1 份 + 案号）', escalated && actionBody.includes(CASE_NO), `我的档案 1 份=${escalated}；含案号=${actionBody.includes(CASE_NO)}`);
  await screenshot(session, 'demo-action-real-files');

  const stepShown = await visible(session, `document.body.innerText.includes('发现问题') || document.body.innerText.includes('发现机会')`, { timeout: 8000, label: '详情渲染步骤' });
  const detailText = await bodyText(session);
  const hasExpert = /经营分析专家|财务专家|销售专家|门店运营专家|经营增长专家|商品专家|数据分析师|会员运营专家/.test(detailText);
  suite.check(
    '⑥ 档案详情有步骤与专家，且编号与洞察一致',
    stepShown && hasExpert && insightTag.includes(CASE_NO) && detailText.includes(CASE_NO),
    `含步骤=${stepShown} 含专家=${hasExpert} 洞察 tag 与档案编号一致=${insightTag.includes(CASE_NO) && detailText.includes(CASE_NO)}`,
  );

  // 迭代 70 起：行动回路**可在演示内走完**（推进 / 归档 / 沉淀经验，见 demo_action_loop_check）。
  // 这条断言改成守「仍未覆盖的写操作照样如实拒绝」+「步骤推进确实在演示内生效」。
  const started = await evaluate(session, `(() => {
    const before = [...document.querySelectorAll('.page.active .timeline button')].filter((x) => x.textContent.trim() === '开始').length;
    const b = [...document.querySelectorAll('.page.active .timeline button')].find((x) => x.textContent.trim() === '开始');
    if (!b) return { before, clicked: false };
    b.click();
    return { before, clicked: true };
  })()`);
  const progressed = await visible(session, `(window.__toastLog || []).some((t) => String(t).startsWith('已开始'))`, { timeout: 6000, label: '演示内推进生效' });
  await sleep(600);
  const afterCount = await evaluate(session, `[...document.querySelectorAll('.page.active .timeline button')].filter((x) => x.textContent.trim() === '开始').length`);
  const refused = await evaluate(session, `(async () => {
    const out = [];
    for (const p of ['/api/datasets', '/api/watch/demo1/check']) {
      const r = await fetch(p, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' });
      const j = await r.json().catch(() => ({}));
      out.push(p + ' → ' + r.status + '|' + (j.detail || ''));
    }
    return out.join(' ／ ');
  })()`);
  suite.check(
    '⑦ 演示内推进生效（点开始 → toast + 待办少一个）；未覆盖的写操作仍如实 409',
    started.clicked && progressed && afterCount === started.before - 1 && String(refused).split(' ／ ').every((l) => l.includes('409')),
    `开始按钮 ${started.before} → ${afterCount}｜toast 生效=${progressed}｜其它写操作=${refused}`,
  );
} catch (err) {
  fatal(err);
}

await finish(suite, [server?.close, chrome?.close]);
