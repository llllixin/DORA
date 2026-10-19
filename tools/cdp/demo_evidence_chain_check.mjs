#!/usr/bin/env node
/**
 * 快照 demo 的「证据链」回归：**点得开**，且打开的是**本条洞察自己的真实证据**。
 *
 * 缘起（2026-09-26 用户实测：「所有的证据链都点不开」）：
 *   快照产物用 `VITE_API_MODE=auto` + 拦截器（见 `frontend/scripts/build-design-demo.mjs`）。
 *   `syncRemoteData()` 靠拦截器成功 → `dataConnection.source='live'` → `getEvidence()` 走
 *   `remoteRead('/evidence/{id}')`，而拦截器**只覆盖 datasets / insights / watch / action-cases**，
 *   于是 9/9 条洞察点「打开证据链」都落到 catch-all 的「未覆盖接口按离线回退」→ 只弹
 *   「证据读取失败：Failed to fetch（…）」，抽屉永不打开（P041）。
 *
 * 修法（仍不改产品代码）：证据链也是**构建期真实快照**的一部分 —— 生成器逐条抓
 *   `GET /api/evidence/{洞察id}` 写进 `snapshot.evidence`，拦截器补 `/api/evidence/{id}` 分支；
 *   快照里没有的 id 如实 404（与后端同形状），不伪造证据。
 *
 * 断言（5）：
 *   ① 快照证据链覆盖**全部**洞察 id（缺一条都算回归 —— 旧缓存就是这样把按钮点死的）
 *   ② 逐条洞察：抽屉打开，标题 = `数据证据链 · <本洞察标题>`（不是上一条的残留）
 *   ③ 逐条洞察：命中证据条数 / 原始行数 == 快照期望，且有「事实 / 判断 / 建议」与「分析路径」
 *   ④ 全程 0 次「证据读取失败」toast（用户报的症状）
 *   ⑤ 脉搏页问题卡的行内「证据链」入口同样可打开；快照里没有的 id 如实 404（不伪造）
 *
 * 用法：node tools/cdp/demo_evidence_chain_check.mjs
 */
import {
  SEED_DATASOURCE, TOAST_OBSERVER, clickByText, createSuite, ensureDemoHtml, evaluate, fatal, finish,
  goto, launchChrome, newPage, preparePage, screenshot, serveStatic, sleep, toastLog, visible,
} from './lib/cdp.mjs';
import path from 'node:path';

const suite = createSuite('demo_evidence_chain_check（快照 demo：证据链点得开且是本条洞察的真实证据）');
let chrome;
let server;

/** 抽屉内容探针：标题 / 命中证据 / 原始行 / 分析路径 / 三段结论。 */
const DRAWER = `(() => {
  const a = document.querySelector('.drawer.open');
  if (!a) return null;
  return {
    title: (a.querySelector('h2')?.textContent ?? '').trim(),
    hits: a.querySelectorAll('.hit').length,
    rows: a.querySelectorAll('table.raw tbody tr').length,
    code: (a.querySelector('.code')?.textContent ?? '').trim(),
    text: a.innerText,
  };
})()`;

try {
  const html = await ensureDemoHtml();
  server = await serveStatic(path.dirname(html));
  chrome = await launchChrome();
  const { session } = await newPage(chrome.port);
  await preparePage(session, { initScripts: [SEED_DATASOURCE, TOAST_OBSERVER] });

  const url = (hash) => `${server.url}/${path.basename(html)}${hash}`;
  await goto(session, url('#page=insight&type=problem&idx=0'), { waitSelector: '.detail-top' });

  if (!(await evaluate(session, '!!window.__DORA_DEMO_SNAPSHOT__'))) {
    console.log('SKIP：当前产物不含真实数据快照（`window.__DORA_DEMO_SNAPSHOT__` 未注入）→ 本用例未跑（不是通过）');
    console.log('  生成方式：DORA_DEMO_API=http://127.0.0.1:8010/api npm run demo:html（需后端在线）');
    await finish(suite, [server?.close, chrome?.close]);
    process.exit(0);
  }

  // 期望值直接取自产物内联的快照（同一份真相，不另造一套）
  const snap = await evaluate(session, `(() => {
    const s = window.__DORA_DEMO_SNAPSHOT__ || {};
    const ev = s.evidence || {};
    const ids = (s.insights || []).map((i) => i.id);
    return {
      evCount: Object.keys(ev).length,
      ids,
      missing: ids.filter((id) => !ev[id]),
      items: (s.insights || []).map((i) => ({
        id: i.id, type: i.type, title: i.title,
        evTitle: ev[i.id] ? ev[i.id].title : null,
        hits: ev[i.id] ? (ev[i.id].hits || []).length : -1,
        rows: ev[i.id] ? (ev[i.id].rawRows || []).length : -1,
      })),
    };
  })()`);

  suite.check(
    '① 快照证据链覆盖全部洞察 id（缺一条都会让按钮点不开）',
    snap.missing.length === 0 && snap.evCount === snap.ids.length,
    `洞察 ${snap.ids.length} 条 / 证据 ${snap.evCount} 条 · 缺=${JSON.stringify(snap.missing)}`,
  );

  // 逐条打开：problem / opportunity / change 三类按快照顺序遍历
  const runs = [];
  for (const type of ['problem', 'opportunity', 'change']) {
    const group = snap.items.filter((i) => i.type === type);
    for (let idx = 0; idx < group.length; idx += 1) {
      await goto(session, url(`#page=insight&type=${type}&idx=${idx}`), { waitSelector: '.detail-top' });
      await sleep(220);
      const shown = await evaluate(session, `(document.querySelector('.detail-title')?.textContent ?? '').trim()`);
      const clicked = await clickByText(session, 'button', '打开证据链');
      const opened = await visible(session, `!!document.querySelector('.drawer.open')`, { timeout: 4000, label: `${type}#${idx} 抽屉打开` });
      const drawer = opened ? await evaluate(session, DRAWER) : null;
      runs.push({ ...group[idx], type, idx, shown, clicked, opened, drawer });
      if (opened && idx === 0) await screenshot(session, `demo-evidence-chain-${type}`);
      if (opened) await evaluate(session, `document.querySelector('.drawer .close')?.click() ?? null`);
      await sleep(120);
    }
  }

  const brief = (r) => `${r.type}#${r.idx}(${r.id})「${r.shown}」抽屉=${r.opened} 标题=${JSON.stringify(r.drawer?.title ?? null)} 命中=${r.drawer?.hits ?? '-'} 行=${r.drawer?.rows ?? '-'}`;

  suite.check(
    '② 逐条洞察：抽屉打开，且标题 = 数据证据链 · 本洞察标题',
    runs.length === snap.ids.length
      && runs.every((r) => r.opened && r.drawer?.title === `数据证据链 · ${r.evTitle}` && r.shown === r.evTitle),
    runs.map(brief).join('｜'),
  );

  suite.check(
    '③ 逐条洞察：命中证据条数 / 原始行数 == 快照期望，且有事实·判断·建议 + 分析路径',
    runs.every((r) => r.drawer
      && r.drawer.hits === r.hits && r.drawer.rows === r.rows
      && ['事实：', '判断：', '建议：'].every((k) => r.drawer.text.includes(k))
      && r.drawer.code.length > 10),
    runs.map((r) => `${r.id} 命中 ${r.drawer?.hits}/${r.hits} 行 ${r.drawer?.rows}/${r.rows} 路径=${JSON.stringify((r.drawer?.code ?? '').slice(0, 24))}`).join('｜'),
  );

  const toasts = await toastLog(session);
  suite.check(
    '④ 全程 0 次「证据读取失败」toast（用户报的症状）',
    !toasts.some((t) => String(t).includes('证据读取失败')),
    `toast 历史=${JSON.stringify(toasts)}`,
  );

  // ⑤ 脉搏页入口 + 缺失 id 的如实 404
  await goto(session, url('#page=pulse'), { waitSelector: '.problem-item' });
  await sleep(400);
  await evaluate(session, `document.querySelector('.problem-evidence button')?.click() ?? null`);
  const pulseOpened = await visible(session, `!!document.querySelector('.drawer.open')`, { timeout: 4000, label: '脉搏卡证据链抽屉' });
  const pulseDrawer = pulseOpened ? await evaluate(session, DRAWER) : null;
  await evaluate(session, `document.querySelector('.drawer .close')?.click() ?? null`);
  const missingStatus = await evaluate(session, `fetch('/api/evidence/__no_such_id__').then((r) => r.status)`);
  const missingBody = await evaluate(session, `fetch('/api/evidence/__no_such_id__').then((r) => r.json()).then((b) => b.detail ?? '')`);
  suite.check(
    '⑤ 脉搏卡入口也能打开；快照没有的 id 如实 404（不伪造证据）',
    pulseOpened && /^数据证据链 · /.test(pulseDrawer?.title ?? '') && missingStatus === 404 && String(missingBody).includes('证据链'),
    `脉搏抽屉标题=${JSON.stringify(pulseDrawer?.title ?? null)}｜未知 id → HTTP ${missingStatus} detail=${JSON.stringify(missingBody)}`,
  );
} catch (err) {
  fatal(err);
}

await finish(suite, [server?.close, chrome?.close]);

