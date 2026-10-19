#!/usr/bin/env node
/**
 * 脉搏页三块面板的布局回归：**左右两列底边对齐（行高由右列内容决定）+ 左卡完整展示 + 只有左卡一层滚动；
 * 右列两卡贴合内容、不滚动**。
 *
 * 缘起（2026-09-26 用户四轮实测反馈）：
 *   ① 三块面板要固定大小、内容超出可滑动 → 定 600px（右列两卡各 294px）；
 *   ② 「业务脉络·问题」初版**窗口太小**（列表被压成 ~122px 只剩一条）且**双层滚动**、行被压扁导致**文字被裁** →
 *      改为：列表**完整展示**（不再自己滚动），只保留**外层（卡片）**一层滚动；卡片子元素与行一律不压缩。
 *   ③ 用户再指出「布局不好看，下面的字太靠边了；监控状态下边界往上一点、本轮工作上边界也上移，两块都不用滑动」→
 *      行内「证据 / 证据链」补 12px 内缩 + 12px 下留白；右列改成**按内容高度**（217 + 348 + 12 = 577 ≤ 左卡 600），
 *      不再「各占一半 294px + 内滚」。
 *   ④ 用户再指出「把左边板块下边界往上一点，确保左右对齐」→ 左卡原来写死 600px、右列内容只有 577px，
 *      底边差 23px。**写死值永远追不上内容高度**，改为让**右列决定行高**、左卡自己撑满
 *      （`.pulse-priority{contain:size}` 使自身内容不参与行高计算 + 默认 `align-self:stretch`）→ 底边差 0。
 *
 * 断言（9）：
 *   ① 左卡与右列**等高且底边对齐**（差 ≤1px），且左卡**外层（卡片）**可滚动（`overflow-y:auto`）
 *   ② 「业务脉络 · 问题」**完整展示**：列表自身不滚动（`overflow-y:visible`，scrollHeight == clientHeight）
 *   ③ 问题行完整：行数 ≥ 1、每行 h ≥ 128、无裁剪（scrollHeight ≤ clientHeight + 2）
 *   ④ 行内「证据 / 证据链」不贴边：证据文字与卡内标题同缩进（12px）、「证据链」按钮距行的右/下内边 ≥ 8px
 *   ⑤ 右列两卡按内容排布且**不滚动**：`overflow-y:visible`、scrollHeight ≤ clientHeight + 2
 *   ⑥ 监控状态卡不再被撑到「各占一半」（h < 284）；「本轮工作」上边界随之上移（在列内偏移 < 294）
 *   ⑦ 两卡合计 + 12px 间距 == 右列高度（== 左卡高度）→ 不滚动就装得下，且两列因此齐平
 *   ⑧ 点击问题行生效：该行 `active selected`，左卡标题切换为该行标题
 *   ⑨ 左卡内容确实高于卡片（scrollHeight > clientHeight）→ 外滚是有意义的
 *
 * 用法：node tools/cdp/demo_pulse_panels_check.mjs
 */
import {
  SEED_DATASOURCE, createSuite, ensureDemoHtml, evaluate, fatal, finish, goto, launchChrome, newPage,
  preparePage, screenshot, serveStatic, sleep,
} from './lib/cdp.mjs';
import path from 'node:path';

const HALF_H = 294; // 迭代 64 的「右列两卡各占一半」（只用于对照：现在必须小于它）
const CARD_GAP = 12; // `.cockpit-side{gap:12px}`
const ALIGN_TOL = 1; // 底边对齐容差（px）：允许 1px 的取整/滚动条误差
const suite = createSuite('demo_pulse_panels_check（脉搏页：左右两列底边对齐 + 左卡外滚 + 右列贴合内容不滚动）');
let chrome;
let server;

const box = (session, sel) => evaluate(
  session,
  `(() => { const e = document.querySelector(${JSON.stringify(sel)}); if (!e) return null; const r = e.getBoundingClientRect(); return { h: Math.round(r.height), top: Math.round(r.top), bottom: Math.round(r.bottom), client: e.clientHeight, scroll: e.scrollHeight, overflowY: getComputedStyle(e).overflowY }; })()`,
);

try {
  const html = await ensureDemoHtml();
  server = await serveStatic(path.dirname(html));
  chrome = await launchChrome();
  const { session } = await newPage(chrome.port);
  await preparePage(session, { initScripts: [SEED_DATASOURCE] });
  await goto(session, `${server.url}/${path.basename(html)}#page=pulse`, { waitSelector: '.priority-title' });

  const left = await box(session, '.pulse-priority');
  const side = await box(session, '.cockpit-side');
  suite.check(
    '① 左右两列等高、底边对齐（行高由右列内容决定），左卡外层可滚动',
    !!left && !!side && Math.abs(left.h - side.h) <= ALIGN_TOL
      && Math.abs(left.bottom - side.bottom) <= ALIGN_TOL && left.overflowY === 'auto',
    `左卡 h=${left?.h} bottom=${left?.bottom} ${left?.overflowY}｜右列 h=${side?.h} bottom=${side?.bottom}`
    + `｜底边差=${left && side ? left.bottom - side.bottom : '-'}px`,
  );

  const list = await box(session, '.problem-list');
  suite.check(
    '② 「业务脉络 · 问题」完整展示（列表自身不滚动）',
    !!list && list.overflowY === 'visible' && list.scroll <= list.client + 2,
    `列表 h=${list?.h} overflowY=${list?.overflowY} scrollHeight=${list?.scroll} clientHeight=${list?.client}`,
  );

  const rows = await evaluate(
    session,
    `[...document.querySelectorAll('.pulse-priority .problem-item')].map((it) => {
      const r = it.getBoundingClientRect();
      const cs = getComputedStyle(it);
      const innerLeft = r.left + parseFloat(cs.borderLeftWidth || 0);
      const innerRight = r.right - parseFloat(cs.borderRightWidth || 0);
      const innerBottom = r.bottom - parseFloat(cs.borderBottomWidth || 0);
      const title = it.querySelector('.problem-toggle .meta b')?.getBoundingClientRect();
      const span = it.querySelector('.problem-evidence span')?.getBoundingClientRect();
      const btn = it.querySelector('.problem-evidence .btn')?.getBoundingClientRect();
      return {
        h: Math.round(r.height), client: it.clientHeight, scroll: it.scrollHeight,
        text: (it.querySelector('b')?.textContent ?? '').slice(0, 20),
        titleInset: title ? Math.round(title.left - innerLeft) : -1,
        evidenceInset: span ? Math.round(span.left - innerLeft) : -1,
        btnRightGap: btn ? Math.round(innerRight - btn.right) : -1,
        btnBottomGap: btn ? Math.round(innerBottom - btn.bottom) : -1,
      };
    })`,
  );
  const clipped = rows.filter((r) => r.scroll > r.client + 2 || r.h < 128);
  suite.check(
    '③ 问题行完整可见（行高 ≥128、无裁剪）',
    rows.length >= 1 && clipped.length === 0,
    `行数=${rows.length}｜行高=${rows.map((r) => r.h).join('/')}｜异常行=${clipped.length}`,
  );

  const tight = rows.filter((r) => r.evidenceInset !== r.titleInset || r.btnRightGap < 8 || r.btnBottomGap < 8);
  suite.check(
    '④ 行内「证据 / 证据链」不贴边（与标题同缩进 12px、按钮留白 ≥8px）',
    rows.length >= 1 && tight.length === 0,
    `首行：标题缩进=${rows[0]?.titleInset} 证据缩进=${rows[0]?.evidenceInset} 按钮右/下留白=${rows[0]?.btnRightGap}/${rows[0]?.btnBottomGap}｜贴边行=${tight.length}`,
  );


  const c1 = await box(session, '.cockpit-side .monitor-card:nth-of-type(1)');
  const c2 = await box(session, '.cockpit-side .monitor-card:nth-of-type(2)');
  suite.check(
    '⑤ 右列两卡按内容排布且不滚动',
    !!c1 && !!c2 && c1.overflowY === 'visible' && c2.overflowY === 'visible'
      && c1.scroll <= c1.client + 2 && c2.scroll <= c2.client + 2,
    `监控状态 h=${c1?.h} ${c1?.overflowY} scroll ${c1?.scroll}/client ${c1?.client}｜本轮工作 h=${c2?.h} ${c2?.overflowY} scroll ${c2?.scroll}/client ${c2?.client}`,
  );

  const c2Offset = c1 && c2 ? c2.top - c1.top : -1;
  suite.check(
    '⑥ 监控状态按内容收缩（不再各占一半）、本轮工作上边界随之上移',
    !!c1 && !!c2 && c1.h < HALF_H - 10 && c2Offset < HALF_H,
    `监控状态 h=${c1?.h}（旧值 ${HALF_H}）｜本轮工作在列内偏移=${c2Offset}（旧值 ${HALF_H + CARD_GAP}）`,
  );

  const stack = c1 && c2 ? c1.h + CARD_GAP + c2.h : -1;
  suite.check(
    '⑦ 两卡合计 + 间距 == 右列高度（== 左卡高度）→ 不滚动装得下、两列因此齐平',
    !!side && !!left && stack > 0 && Math.abs(stack - side.h) <= ALIGN_TOL
      && Math.abs(side.h - left.h) <= ALIGN_TOL,
    `监控状态 ${c1?.h} + 间距 ${CARD_GAP} + 本轮工作 ${c2?.h} = ${stack}｜右列 h=${side?.h}／左卡 h=${left?.h}`,
  );

  const secondTitle = rows[1]?.text ?? '';
  const clicked = await evaluate(
    session,
    `(() => { const items = document.querySelectorAll('.pulse-priority .problem-item'); const it = items[1]; if (!it) return false; it.querySelector('.problem-toggle').click(); return true; })()`,
  );
  await sleep(400);
  const state = await evaluate(
    session,
    `(() => { const it = document.querySelectorAll('.pulse-priority .problem-item')[1]; return { cls: it?.className ?? '', hero: document.querySelector('.pulse-priority .priority-title')?.textContent ?? '' }; })()`,
  );
  suite.check(
    '⑧ 点击问题行生效（行选中 + 左卡切换到该问题）',
    clicked && /active/.test(state.cls) && /selected/.test(state.cls) && state.hero.includes(secondTitle.slice(0, 6)),
    `行类="${state.cls}" 左卡标题="${state.hero}" 期望含「${secondTitle}」`,
  );

  const afterClick = await box(session, '.pulse-priority');
  suite.check(
    '⑨ 卡片内容高于卡片 → 外层滑动有意义',
    !!afterClick && afterClick.scroll > afterClick.client,
    `卡片 scrollHeight=${afterClick?.scroll} > clientHeight=${afterClick?.client}`,
  );

  await screenshot(session, 'demo-pulse-panels');
} catch (err) {
  fatal(err);
}

await finish(suite, [server?.close, chrome?.close]);

