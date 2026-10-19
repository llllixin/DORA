#!/usr/bin/env node
/**
 * 洞察页「事实 · 具体数据」列的高度回归：**被等高拉伸时不留空洞**（关键数值升级为 hero 大数字 +
 * 整组事实收进一个会随行高伸缩的面板）。
 *
 * 缘起（2026-09-26 用户实测反馈）：
 *   ① 左卡（事实）真正的内容只有 213px，右卡（判断）有 450px；`.judge-grid{align-items:stretch}`
 *      把事实列拉到 452px → **卡片底部留 239px 空洞**（9 条洞察全中）。
 *   ② 用户提示「可以让关键数值等字体放大一点或者别的方案」→ 试了 5 类改法（整组事实伸缩面板 /
 *      单块 hero / 内容上下平摊 / 因素卡撑满 / 列不拉伸），比对截图后定稿：
 *      a) 关键数值 12px → 40px hero 大数字；
 *      b) 整组事实（关键数值 + 触发条件 + 证据来源）收进 `.judge-facts .ev-list` 面板，
 *         让**面板**去吃多余高度（flex:1 + 内容居中）→ 空白变成面板内边距，而不是卡片尾部的空洞；
 *      c) 面板底色跟洞察类型（问题红 / 机会绿 / 变化蓝），需 :has()；不支持时退回中性淡紫，仍可读。
 *
 * 断言（8）：
 *   ① 三种类型都「两列等高、底边对齐」（差 ≤1px）—— 空洞是靠面板吸收，而不是靠列不等高躲开
 *   ② 三种类型的事实列都**没有大空洞**：顶层子块之间的空带 ≤ 24px（改前 239px）
 *   ③ 关键数值都是 hero 层级：字号 ≥ 32px、不横向溢出（长值最多折 2 行）
 *   ④ 面板确实在吃剩余高度：面板高 + 12px 间距 + 因素卡高 == 事实列高 − 内边距 − 标题行
 *   ⑤ 面板底色随类型区分：问题 = 红 soft、机会 = 绿 soft、变化 = 蓝 soft（三者互不相同）
 *   ⑥ 因素卡数值放大（≥ 20px）但不压过 hero（< hero 字号），层级不打架
 *   ⑦ 不是靠撑高页面消除空洞：详情卡总高仍 ≤ 720px（迭代 66 两列实测 696）
 *   ⑧ 判断列零回归：结论 14.5px / 后果 12.5px / 置信度 15px 与「≥5 块结构」不变
 *
 * 用法：node tools/cdp/demo_insight_facts_check.mjs
 */
import {
  SEED_DATASOURCE, createSuite, ensureDemoHtml, evaluate, fatal, finish, goto, launchChrome, newPage,
  preparePage, serveStatic, sleep,
} from './lib/cdp.mjs';
import path from 'node:path';
import { mkdirSync, writeFileSync } from 'node:fs';

const ARTIFACTS = path.join(import.meta.dirname, '.artifacts');
const GAP = 12; // `.cause-grid{margin-top:12px}`（面板与因素卡之间的设计间距）
const BAND_TOL = 24; // 顶层子块之间允许的最大空带（= 卡内「空洞」判据；设计间距只有 9 / 12px）
const CARD_H_MAX = 720; // 详情卡总高上限（迭代 66 两列实测 696）
const SUITE = [
  // 三种类型各取一条：面板底色必须跟着类型走（问题红 / 机会绿 / 变化蓝）
  { type: 'problem', idx: 0, soft: 'rgb(255, 240, 243)', label: '问题（红）' },
  { type: 'opportunity', idx: 0, soft: 'rgb(236, 250, 244)', label: '机会（绿）' },
  { type: 'change', idx: 0, soft: 'rgb(237, 244, 255)', label: '变化（蓝）' },
];

const suite = createSuite('demo_insight_facts_check（洞察「事实 · 具体数据」：等高不空洞 + 关键数值 hero + 类型配色）');
let chrome;
let server;

/** 一条洞察的事实/判断列量测：尺寸、空带、面板、字号、颜色、页面高度。 */
const MEASURE = `(() => {
  const grid = document.querySelector('.judge-grid');
  if (!grid) return null;
  const facts = [...grid.children].find((c) => !c.classList.contains('verdict'));
  const verdict = [...grid.children].find((c) => c.classList.contains('verdict'));
  if (!facts || !verdict) return null;
  const r = (e) => { const b = e.getBoundingClientRect(); return { top: Math.round(b.top), bottom: Math.round(b.bottom), h: Math.round(b.height) }; };
  const kids = [...facts.children].map((k) => ({ cls: k.className.split(' ').pop(), ...r(k) }));
  const panel = facts.querySelector('.ev-list');
  const hero = facts.querySelector('.ev-row:first-child span');
  const card = facts.querySelector('.cause-item');
  const fcs = getComputedStyle(facts);
  const heroCS = getComputedStyle(hero);
  const lead = verdict.querySelector('.verdict-lead');
  const consq = verdict.querySelector('.consq-summary');
  const conf = verdict.querySelector('.verdict-bar b');
  return {
    title: document.querySelector('.detail-title')?.textContent ?? '',
    facts: r(facts), verdict: r(verdict),
    bands: kids.slice(1).map((k, i) => k.top - kids[i].bottom),
    headH: kids[0].h + parseFloat(getComputedStyle(facts.children[0]).marginBottom || 0), // 标题行 + 它与面板之间的设计间距
    padV: parseFloat(fcs.paddingTop) + parseFloat(fcs.paddingBottom),
    panelH: Math.round(panel.getBoundingClientRect().height),
    panelGrow: getComputedStyle(panel).flexGrow,
    panelBg: getComputedStyle(panel).backgroundColor,
    heroFont: parseFloat(heroCS.fontSize),
    heroLines: Math.round(hero.getBoundingClientRect().height / parseFloat(heroCS.lineHeight)),
    heroOverflow: hero.scrollWidth > hero.clientWidth + 1,
    heroText: hero.textContent,
    factorFont: parseFloat(getComputedStyle(card.querySelector('em')).fontSize),
    factorH: Math.round(card.getBoundingClientRect().height),
    cardH: Math.round(document.querySelector('.detail-bottom.one-col').getBoundingClientRect().height),
    leadFont: lead ? parseFloat(getComputedStyle(lead).fontSize) : 0,
    consqFont: consq ? parseFloat(getComputedStyle(consq).fontSize) : 0,
    confFont: conf ? parseFloat(getComputedStyle(conf).fontSize) : 0,
    verdictBlocks: [...verdict.children].filter((c) => !c.classList.contains('jc-head')).length,
  };
})()`;


/** 证据截图：只裁「事实 · 具体数据」那半张卡（整页截图里这处差别看不出来）。 */
async function shotFacts(session, name) {
  const rect = await evaluate(session, `(() => {
    const facts = [...document.querySelector('.judge-grid').children].find((c) => !c.classList.contains('verdict'));
    const b = facts.getBoundingClientRect();
    return { x: Math.max(0, b.left - 10), y: Math.max(0, b.top + window.scrollY - 10), width: b.width + 20, height: b.height + 20 };
  })()`);
  const shot = await session.send('Page.captureScreenshot', {
    format: 'png', captureBeyondViewport: true, clip: { ...rect, scale: 1 },
  });
  mkdirSync(ARTIFACTS, { recursive: true });
  const file = path.join(ARTIFACTS, `${name}.png`);
  writeFileSync(file, Buffer.from(shot.data, 'base64'));
  console.log(`· 截图（证据）：${path.relative(process.cwd(), file)}`);
}

try {
  const html = await ensureDemoHtml();
  server = await serveStatic(path.dirname(html));
  chrome = await launchChrome();
  const { session } = await newPage(chrome.port);
  await preparePage(session, { initScripts: [SEED_DATASOURCE] });
  const base = `${server.url}/${path.basename(html)}#page=insight`;

  const runs = [];
  for (const t of SUITE) {
    await goto(session, `${base}&type=${t.type}&idx=${t.idx}`, { waitSelector: '.judge-grid' });
    await sleep(600); // 等 /api/dora/chat 兜底落定（「历史先例」行会影响列内容高度）
    runs.push({ ...t, m: await evaluate(session, MEASURE) });
  }
  const brief = (r) => `${r.label}「${r.m?.title ?? '?'}」h=${r.m?.facts.h}/${r.m?.verdict.h} 底边差=${r.m ? Math.abs(r.m.facts.bottom - r.m.verdict.bottom) : '-'}`;

  suite.check(
    '① 三种类型都两列等高、底边对齐（差 ≤1px）',
    runs.every((r) => r.m && Math.abs(r.m.facts.h - r.m.verdict.h) <= 1 && Math.abs(r.m.facts.bottom - r.m.verdict.bottom) <= 1),
    runs.map(brief).join('｜'),
  );

  suite.check(
    '② 事实列无空洞：顶层子块之间的空带 ≤ 24px（改前 239px）',
    runs.every((r) => r.m && r.m.bands.every((b) => b <= BAND_TOL)),
    runs.map((r) => `${r.label} 空带=${JSON.stringify(r.m?.bands)}`).join('｜'),
  );

  suite.check(
    '③ 关键数值已是 hero 大数字（≥32px）且不横向溢出',
    runs.every((r) => r.m && r.m.heroFont >= 32 && !r.m.heroOverflow && r.m.heroLines <= 2),
    runs.map((r) => `${r.label} ${r.m?.heroFont}px 行数=${r.m?.heroLines} “${r.m?.heroText}”`).join('｜'),
  );

  suite.check(
    '④ 面板在吃剩余高度（面板 + 12px 间距 + 因素卡 == 列高 − 内边距 − 标题行）',
    runs.every((r) => r.m && r.m.panelGrow === '1'
      && Math.abs(r.m.panelH - (r.m.facts.h - r.m.padV - r.m.headH - GAP - r.m.factorH)) <= 3),
    runs.map((r) => `${r.label} 面板=${r.m?.panelH} 应有的=${r.m ? r.m.facts.h - r.m.padV - r.m.headH - GAP - r.m.factorH : '-'} flex-grow=${r.m?.panelGrow}`).join('｜'),
  );

  const distinct = new Set(runs.map((r) => r.m?.panelBg)).size === runs.length;
  suite.check(
    '⑤ 面板底色随类型区分（问题红 / 机会绿 / 变化蓝）',
    distinct && runs.every((r) => r.m && r.m.panelBg === r.soft),
    runs.map((r) => `${r.label} 实际=${r.m?.panelBg} 期望=${r.soft}`).join('｜') + `｜三者互不相同=${distinct}`,
  );

  suite.check(
    '⑥ 因素卡数值放大（≥20px）但不压过 hero（< hero 字号）',
    runs.every((r) => r.m && r.m.factorFont >= 20 && r.m.factorFont < r.m.heroFont),
    runs.map((r) => `${r.label} 因素 ${r.m?.factorFont}px < hero ${r.m?.heroFont}px`).join('｜'),
  );

  suite.check(
    '⑦ 不是靠撑高页面消除空洞（详情卡总高 ≤ 720px）',
    runs.every((r) => r.m && r.m.cardH <= CARD_H_MAX),
    runs.map((r) => `${r.label} 详情卡 h=${r.m?.cardH}`).join('｜'),
  );

  suite.check(
    '⑧ 判断列零回归（结论 14.5px / 后果 12.5px / 置信度 15px / ≥5 块结构）',
    runs.every((r) => r.m && r.m.leadFont === 14.5 && r.m.consqFont === 12.5 && r.m.confFont === 15 && r.m.verdictBlocks >= 5),
    runs.map((r) => `${r.label} 结论/后果/置信=${r.m?.leadFont}/${r.m?.consqFont}/${r.m?.confFont} 块=${r.m?.verdictBlocks}`).join('｜'),
  );

  for (const r of runs) {
    await goto(session, `${base}&type=${r.type}&idx=${r.idx}`, { waitSelector: '.judge-grid' });
    await sleep(600);
    await shotFacts(session, `demo-insight-facts-${r.type}`);
  }
} catch (err) {
  fatal(err);
}

await finish(suite, [server?.close, chrome?.close]);
