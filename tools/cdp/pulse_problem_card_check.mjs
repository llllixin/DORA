#!/usr/bin/env node
/**
 * 脉搏页问题卡收敛回归（真 demo 页面，change `pulse-problem-card-cleanup`）。
 *
 * 缘起：2026-09-26 用户实测指出两处 ——
 *   ① 「让 Dora 帮我跟进」一键委托入口没有逻辑（离线必然禁用；且按洞察固定拼文本直写 `/api/watch`，
 *      绕过持续关注页「解析 → 显式确认 → 选频率」流程）；
 *   ② 问题卡迷你块里的「Dora 正在替你持续检查（真实委托）」在离线是自我否定的假声明
 *      （spec：离线不出现未真实发生的状态；来源委托已移交的问题卡 SHALL NOT 出现该文案）。
 *
 * 断言（8）：
 *   ① 首屏问题卡不再出现「让 Dora 帮我跟进」
 *   ② 遍历**每一条**问题（逐条切换当前问题）后该入口都不出现
 *   ③ 问题卡主按钮集合始终含两个真实动作（进入洞察 / 证据链），且无清单外的按钮
 *   ④ 问题卡（含迷你块）不再出现「正在替你持续检查」与「真实委托」
 *   ⑤ 问题卡不再出现「已加入跟进 ✓ / 取消委托」（change `pulse-hero-drop-follow-actions`）
 *   ⑥ 问题卡不再出现「自动监控 / 管理 →」委托块（同上）
 *   ⑦ 摘要卡不再声称「正在替你持续检查」（change `pulse-summary-delegate-copy`）
 *   ⑧ 持续关注页仍是建档入口（委托输入框 +「让 Dora 理解」）
 *
 * 用法：node tools/cdp/pulse_problem_card_check.mjs
 */
import {
  SEED_DATASOURCE, bodyText, createSuite, ensureDemoHtml, evaluate, fatal, finish, goto, launchChrome,
  newPage, preparePage, screenshot, serveStatic, textOf, visible,
} from './lib/cdp.mjs';
import path from 'node:path';

const REMOVED_ENTRY = '让 Dora 帮我跟进';
const REMOVED_CLAIM = '正在替你持续检查';
const SELF_REFUTING = '真实委托';
/** 问题卡主按钮区允许出现的动作（真实可走通；spec 变化时同步维护此清单）。 */
const ALLOWED_HERO_ACTIONS = [
  '进入当前问题洞察 →',
  '查看当前问题证据链',
  '已升级移交 ✓',
  '查看委托记录 →',
];

const suite = createSuite('pulse_problem_card_check（单文件 demo · 脉搏页问题卡）');
let chrome;
let server;

try {
  const html = await ensureDemoHtml();
  server = await serveStatic(path.dirname(html));
  chrome = await launchChrome();
  const { session } = await newPage(chrome.port);
  // demo 首开停在「数据入口」页（没有上传数据），用例自己预置数据源以便直接进页面
  await preparePage(session, { initScripts: [SEED_DATASOURCE] });
  await goto(session, `${server.url}/${path.basename(html)}#page=pulse`, { waitSelector: '.priority-title' });

  // 数据落定（P030）：等监控卡有内容或显式空态，而不是等骨架出现
  const settled = await visible(
    session,
    `document.querySelector('.monitor-list')?.children.length > 0 || document.body.innerText.includes('暂无在手持续关注委托')`,
    { timeout: 10000, label: '脉搏页数据落定（监控卡内容或空态）' },
  );
  if (!settled) throw new Error('脉搏页数据未落定（监控卡既无内容也无空态文案）');

  const firstBody = await bodyText(session);
  suite.check('① 首屏问题卡不再出现「让 Dora 帮我跟进」', !firstBody.includes(REMOVED_ENTRY), `body 含该文案=${firstBody.includes(REMOVED_ENTRY)}`);

  const problemCount = await evaluate(session, `document.querySelectorAll('.problem-toggle').length`);
  const walk = [];
  let entryLeak = false;
  let claimLeak = '';
  let missingAction = '';
  let unknownAction = '';
  let followActionLeak = '';
  let delegateBlockLeak = '';

  for (let i = 0; i < problemCount; i += 1) {
    const title = await evaluate(
      session,
      `(() => { const el = document.querySelectorAll('.problem-toggle')[${i}]; el.click(); return (el.querySelector('b')?.textContent ?? '').trim(); })()`,
    );
    await visible(
      session,
      `document.querySelector('.pulse-priority .priority-title')?.textContent.trim() === ${JSON.stringify(title)}`,
      { timeout: 5000, label: `当前问题切到「${title}」` },
    );
    const heroText = await textOf(session, '.pulse-priority');
    const labels = await evaluate(session, `[...document.querySelectorAll('.pulse-priority .main-buttons button')].map((b) => b.innerText.trim())`);
    walk.push(`${title} → ${labels.join(' / ') || '(无按钮)'}`);
    if (heroText.includes(REMOVED_ENTRY)) entryLeak = true;
    if (heroText.includes(REMOVED_CLAIM)) claimLeak = `「${title}」问题卡仍含「${REMOVED_CLAIM}」`;
    if (heroText.includes(SELF_REFUTING)) claimLeak = `「${title}」问题卡仍含「${SELF_REFUTING}」`;
    if (heroText.includes('已加入跟进') || heroText.includes('取消委托')) followActionLeak = `「${title}」问题卡仍有跟进动作`;
    if (heroText.includes('自动监控') || heroText.includes('管理 →')) delegateBlockLeak = `「${title}」问题卡仍有委托块`;
    for (const need of ['进入当前问题洞察 →', '查看当前问题证据链']) {
      if (!labels.includes(need)) missingAction = `「${title}」缺「${need}」`;
    }
    for (const label of labels) {
      if (!ALLOWED_HERO_ACTIONS.includes(label)) unknownAction = `「${title}」出现清单外按钮「${label}」`;
    }
  }

  suite.check('② 遍历全部问题卡（逐条切换当前问题）入口都不出现', problemCount >= 1 && !entryLeak, `共 ${problemCount} 条：${walk.join(' ｜ ')}`);
  suite.check('③ 两个真实动作始终在，且无清单外的按钮', !missingAction && !unknownAction, missingAction || unknownAction || `允许清单内：${ALLOWED_HERO_ACTIONS.join(' / ')}`);

  const body = await bodyText(session);
  suite.check(
    '④ 问题卡（含迷你块）不再出现「正在替你持续检查」/「真实委托」',
    !claimLeak,
    claimLeak || '所有问题卡均无该声明',
  );
  if (body.includes(REMOVED_CLAIM)) {
    console.log('· 范围外事实：持续关注计数卡的描述文案仍写「Dora 正在替你持续检查」（离线镜像口径，本次未改；若要一并收敛需单独拍板）');
  }
  suite.check('⑤ 问题卡不再出现「已加入跟进 ✓ / 取消委托」', !followActionLeak, followActionLeak || '三张问题卡均无跟进动作');
  suite.check('⑥ 问题卡不再出现「自动监控 / 管理 →」委托块', !delegateBlockLeak, delegateBlockLeak || '三张问题卡均无委托块');

  const tileLeak = await evaluate(session, `[...document.querySelectorAll('.summary-card')].map((c) => c.innerText.replace(/\\s+/g, ' ')).filter((t) => t.includes('${REMOVED_CLAIM}'))`);
  suite.check('⑦ 摘要卡不再声称「正在替你持续检查」', tileLeak.length === 0, tileLeak.length ? `仍有：${tileLeak.join(' ｜ ')}` : '四张摘要卡均无该声明');

  await goto(session, `${server.url}/${path.basename(html)}#page=watch`, { waitSelector: '#watchInput' });
  const entry = await evaluate(
    session,
    `(() => ({ input: !!document.querySelector('#watchInput'), parse: [...document.querySelectorAll('button')].some((b) => b.innerText.includes('让 Dora 理解')) }))()`,
  );
  suite.check('⑧ 持续关注页仍是建档入口（输入框 +「让 Dora 理解」）', entry.input && entry.parse, JSON.stringify(entry));

  await screenshot(session, 'pulse-problem-card');
} catch (err) {
  fatal(err);
}

await finish(suite, [server?.close, chrome?.close]);
