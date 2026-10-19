#!/usr/bin/env node
/**
 * demo「冷启动」回归：**标注好的演示页 + 自动载入内置数据**（评审不需要上传任何文件）。
 *
 * 缘起（2026-09-26 用户：「这个页面标注好 demo，请直接载入内部数据，不要让自己上传，下面的小字没对上/不居中」）：
 *   迭代 63 起 demo 首开停在「数据入口」页；但那张页面上 ① 没有演示标注、② 主视觉是
 *   「点击选择或拖入经营数据文件」而单文件 demo 根本解析不了真实文件（拦截器对 `/api/datasets` 一律 409）、
 *   ③ 底部小字写「后端在线：上传按…真实解析入库」——与演示不符，且贴着左下、与整页居中的构图不齐。
 *   本轮（只改 demo 生成脚本，产品代码未动）改为：页面标注「演示模式 · 数据已内置」、隐藏上传入口、
 *   小字换成演示文案并居中，页面**自己载入内置样例数据** → 首开即进入业务脉搏。
 *
 * 断言（5）：
 *   ① 首屏是「数据入口」页，且标题行带「演示模式 · 数据已内置」标注
 *   ② 本页没有上传入口（拖放区 / file input / 「或」分隔都不可见），只剩「载入内置样例数据」一个动作
 *   ③ 底部小字是演示文案（含「无需上传文件」）、整行居中、标签与文字垂直居中对齐
 *   ④ 无需任何点击 → 自动载入内置数据并进入业务脉搏（toast 报「数据就绪」）
 *   ⑤ 数据就绪后只有洞察（行动 0 份 / 关注 0 条）
 *
 * 用法：node tools/cdp/demo_cold_start_check.mjs
 */
import {
  TOAST_OBSERVER, bodyText, createSuite, ensureDemoHtml, evaluate, fatal, finish, goto, launchChrome,
  newPage, preparePage, screenshot, serveStatic, toastLog, visible,
} from './lib/cdp.mjs';
import path from 'node:path';

const suite = createSuite('demo_cold_start_check（demo 冷启动：标注演示 + 自动载入内置数据）');
let chrome;
let server;

/** 冷启动页探针：演示标注 / 上传入口可见性 / 小字文案与对齐。 */
const BOOT = `(() => {
  const vis = (el) => { if (!el) return false; const b = el.getBoundingClientRect(); const cs = getComputedStyle(el); return b.width > 0 && b.height > 0 && cs.display !== 'none' && cs.visibility !== 'hidden'; };
  const card = document.querySelector('.boot-card');
  if (!card) return null;
  const eyebrow = document.querySelector('.boot-head .eyebrow');
  const note = document.querySelector('.boot-note');
  const chip = document.querySelector('.boot-note .tag');
  const post = document.querySelector('.boot-note > span:not(.tag)');
  const cy = (el) => { const b = el.getBoundingClientRect(); return Math.round(((b.top + b.bottom) / 2) * 10) / 10; };
  return {
    label: eyebrow ? getComputedStyle(eyebrow, '::after').content : '',
    dropVisible: vis(document.querySelector('.up-drop')),
    fileVisible: vis(document.querySelector('.up-drop input[type=file]')),
    orVisible: vis(document.querySelector('.up-or')),
    sampleVisible: vis(document.querySelector('.up-sample')),
    sampleLabel: (document.querySelector('.up-sample')?.textContent ?? '').trim(),
    noteText: (post?.textContent ?? '').trim(),
    noteAlign: note ? getComputedStyle(note).textAlign : '',
    noteJustify: note ? getComputedStyle(note).justifyContent : '',
    noteW: note ? Math.round(note.getBoundingClientRect().width) : 0,
    chipCy: chip ? cy(chip) : -99,
    textCy: post ? cy(post) : -99,
  };
})()`;

try {
  const html = await ensureDemoHtml();
  server = await serveStatic(path.dirname(html));
  chrome = await launchChrome();
  const { session } = await newPage(chrome.port);
  // 注意：**不注入** SEED_DATASOURCE —— 本用例验证的正是"首次打开（没有数据源记忆）"时的行为
  await preparePage(session, { initScripts: [TOAST_OBSERVER] });
  const url = (hash = '') => `${server.url}/${path.basename(html)}${hash}`;

  await goto(session, url(), { waitSelector: '.boot-card' });
  const boot = await evaluate(session, BOOT); // 自动载入在 1200ms 后触发，先读这张页
  await screenshot(session, 'demo-cold-start'); // 趁自动载入前留下「标注好的冷启动页」证据

  suite.check(
    '① 首屏是「数据入口」页，且带「演示模式 · 数据已内置」标注',
    !!boot && boot.label.includes('演示模式'),
    `标注=${JSON.stringify(boot?.label ?? null)}`,
  );

  suite.check(
    '② 本页没有上传入口（只剩「载入内置样例数据」一个动作）',
    !!boot && !boot.dropVisible && !boot.fileVisible && !boot.orVisible && boot.sampleVisible,
    `拖放区=${boot?.dropVisible} 文件框=${boot?.fileVisible}「或」=${boot?.orVisible} 样例按钮=${boot?.sampleVisible} 文案=${JSON.stringify(boot?.sampleLabel ?? '')}`,
  );

  suite.check(
    '③ 底部小字是演示文案、整行居中、标签与文字垂直居中对齐',
    !!boot && boot.noteText.includes('无需上传文件') && boot.noteAlign === 'center' && boot.noteJustify === 'center'
      && boot.noteW <= 622 && Math.abs(boot.chipCy - boot.textCy) <= 6,
    `文案=${JSON.stringify(boot?.noteText ?? '')}｜text-align=${boot?.noteAlign} justify=${boot?.noteJustify} 宽=${boot?.noteW}｜标签/文字中线 ${boot?.chipCy}/${boot?.textCy}`,
  );

  const entered = await visible(session, `!!document.querySelector('.priority-title')`, { timeout: 15000, label: '自动载入后进入业务脉搏' });
  const toasts = await toastLog(session);
  suite.check(
    '④ 无需点击 → 自动载入内置数据并进入业务脉搏',
    entered && toasts.some((t) => String(t).includes('数据就绪')),
    `进入脉搏=${entered}｜toast=${JSON.stringify(toasts)}`,
  );

  // 快照产物的语义：数据就绪后**只有洞察**（没有任何行动与关注）；mock 产物不适用本断言
  const hasSnapshot = await evaluate(session, '!!window.__DORA_DEMO_SNAPSHOT__');
  await goto(session, url('#page=action'), { waitSelector: '.page.active' });
  const rendered = await visible(session, `document.querySelector('.page.active')?.innerText.trim().length > 0`, { timeout: 10000, label: '行动回路渲染' });
  const actionBody = await bodyText(session);
  await goto(session, url('#page=watch'), { waitSelector: '.page.active' });
  const watchBody = await bodyText(session);
  const actionEmpty = actionBody.includes('我的档案 0 份');
  const watchEmpty = watchBody.includes('0 个业务目标持续关注中');
  suite.check(
    '⑤ 数据就绪后只有洞察（行动 0 份 / 关注 0 条）',
    hasSnapshot ? (rendered && actionEmpty && watchEmpty) : true,
    `产物含快照=${hasSnapshot}｜行动空=${actionEmpty}｜关注空=${watchEmpty}${hasSnapshot ? '' : '（mock 产物不适用本断言）'}`,
  );
} catch (err) {
  fatal(err);
}

await finish(suite, [server?.close, chrome?.close]);

