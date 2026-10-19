#!/usr/bin/env node
/**
 * 快照 demo 的「行动回路走到底」回归：加入 → 逐步推进 → 归档 → 沉淀经验 → **知识库可见**。
 *
 * 缘起（2026-09-26 用户要求）：「我希望能走完行动回路完成知识库归档」。
 *   此前 demo 只支持「加入行动回路」：步骤推进 / 验证 / 沉淀经验一律 409「这是只读演示」，闭环走不到底。
 *   本轮（仍只改 demo 生成脚本，产品代码零改动）在演示状态里实现了与后端 `app/action/flow.py`
 *   **同一契约**的状态机：`steps/{seq}/start|done|blocked`、`steps/{seq}/experts`、`verify`、
 *   `archive-as-lesson`；归档即按案件类型写知识（A2 同款），沉淀经验再写一条「经验」；
 *   非法迁移同样 400（不伪装成功）、resolved 冻结、状态存 sessionStorage（刷新保留、关标签即重置）。
 *
 * 断言（9）：
 *   ① 加入行动回路后是「执行中」，5 步状态与后端快照一致（已完成/已完成/进行中/待办/待办）
 *   ② 逐步推进符合状态机；全部完成 → 档案「待验证」
 *   ③ 「待验证」时提供验证输入与「归档 · 问题解决 / 继续观察」
 *   ④ **未填验证说明点归档被拒**（400 + 报错提示，状态仍「待验证」）—— 不伪装成功
 *   ⑤ 填说明归档 → 档案「已归档」、archive 追加验证记录、步骤推进被冻结
 *   ⑥ 归档即入库：知识库出现「问题」条目（PRF-0831，结论 = 验证说明）
 *   ⑦ 沉淀经验 → 知识库出现「经验」条目，且不重复计数
 *   ⑧ 整页刷新后状态保留（sessionStorage）：档案仍「已归档」、知识库仍 2 条
 *   ⑨ 已归档档案的推进接口如实 400（冻结，不伪装成功）
 *   ⑩ **「更新数据 → 清除数据」时演示状态一并重置**：回到数据入口页 + sessionStorage 清空 +
 *      重新载入内置数据后行动回路 0 份、知识库 0 条（下一位评审拿到干净起点）
 *
 * 用法：node tools/cdp/demo_action_loop_check.mjs
 */
import {
  SEED_DATASOURCE, TOAST_OBSERVER, clickByText, createSuite, ensureDemoHtml, evaluate, fatal, finish,
  goto, launchChrome, newPage, preparePage, screenshot, serveStatic, sleep, toastLog, bodyText, visible,
} from './lib/cdp.mjs';
import path from 'node:path';

const CASE_NO = 'PRF-0831';
const VERIFY_NOTE = '利润率回到 18.6%，验证通过';
const LESSON_NOTE = '供应商议价 + 采购口径复核可复用于同类成本问题';
const suite = createSuite('demo_action_loop_check（走完行动回路 → 归档 → 知识库）');
let chrome;
let server;

/** 档案探针：状态 / 步骤状态 / 可用动作 / 验证与沉淀入口。 */
const CASE = `(() => {
  const rows = [...document.querySelectorAll('.timeline .tl')].map((tl) => ({
    status: (tl.querySelector('.tl-head .tag')?.textContent ?? '').trim(),
    actions: [...tl.querySelectorAll('.tl-actions button')].map((b) => b.textContent.trim()),
  }));
  return {
    state: ([...document.querySelectorAll('small')].map((s) => s.textContent.trim()).find((t) => t.startsWith('状态 · ')) ?? ''),
    steps: rows.map((r) => r.status),
    canStart: rows.filter((r) => r.actions.includes('开始')).length,
    canDone: rows.filter((r) => r.actions.includes('完成')).length,
    canBlock: rows.filter((r) => r.actions.includes('受阻')).length,
    hasExpertAdd: !!document.querySelector('.add-mini'),
    hasVerify: !!document.querySelector('input[placeholder^="填写验证说明"]'),
    learned: document.body.innerText.includes('已沉淀到知识库'),
    archive: (document.querySelector('pre')?.textContent ?? '').trim(),
  };
})()`;

/** 知识库探针：当前视图条数 / 各类型计数 / 条目要点。 */
const KB = `(() => {
  const cards = [...document.querySelectorAll('.card')].filter((c) => c.querySelector('.tag'));
  return {
    filters: [...document.querySelectorAll('.freq-chip')].map((b) => b.textContent.trim()),
    entries: cards.map((c) => ({
      type: (c.querySelector('.tag')?.textContent ?? '').trim(),
      title: (c.querySelector('b')?.textContent ?? '').trim(),
      meta: (c.querySelector('small')?.textContent ?? '').trim(),
      note: ((c.textContent ?? '').match(/结论：[^\\n]*/) ?? [''])[0],
    })),
  };
})()`;

/** 点某一步的动作按钮（按步序号 + 文案）。 */
const clickStep = (session, seq, label) => evaluate(session, `(() => {
  const tl = document.querySelectorAll('.timeline .tl')[${seq}];
  if (!tl) return false;
  const b = [...tl.querySelectorAll('.tl-actions button')].find((x) => x.textContent.trim() === ${JSON.stringify(label)});
  if (!b) return false;
  b.click();
  return true;
})()`);

/** React 受控输入：必须用原生 setter + input 事件，onChange 才收得到。 */
const typeInto = (session, sel, value) => evaluate(session, `(() => {
  const el = document.querySelector(${JSON.stringify(sel)});
  if (!el) return null;
  const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
  setter.call(el, ${JSON.stringify(value)});
  el.dispatchEvent(new Event('input', { bubbles: true }));
  return el.value;
})()`);

try {
  const html = await ensureDemoHtml();
  server = await serveStatic(path.dirname(html));
  chrome = await launchChrome();
  const { session } = await newPage(chrome.port);
  await preparePage(session, { initScripts: [SEED_DATASOURCE, TOAST_OBSERVER] });
  const url = (hash = '') => `${server.url}/${path.basename(html)}${hash}`;

  // ① 加入行动回路
  await goto(session, url('#page=insight&type=problem&idx=0'), { waitSelector: '.detail-top' });
  await sleep(250);
  await clickByText(session, '.main-buttons button', '加入行动回路');
  await sleep(1100);
  await goto(session, url('#page=action'), { waitSelector: '.timeline' });
  await sleep(900);
  let c = await evaluate(session, CASE);
  suite.check(
    '① 加入后档案为「执行中」，5 步状态与快照一致（已完成/已完成/进行中/待办/待办）',
    c.state.includes('执行中') && c.steps.join(',') === '已完成,已完成,进行中,待办,待办',
    `状态=${c.state}｜步骤=${c.steps.join(',')}`,
  );

  // ② 逐步推进到「待验证」
  const trace = [];
  let guard = 0;
  while (!c.hasVerify && guard < 14) {
    guard += 1;
    const rows = await evaluate(session, `[...document.querySelectorAll('.timeline .tl')].map((x) => [...x.querySelectorAll('.tl-actions button')].map((b) => b.textContent.trim()))`);
    const startIdx = rows.findIndex((a) => a.includes('开始'));
    const doneIdx = rows.findIndex((a) => a.includes('完成'));
    const seq = startIdx >= 0 ? startIdx : doneIdx;
    const label = startIdx >= 0 ? '开始' : '完成';
    if (seq < 0) break;
    await clickStep(session, seq, label);
    await sleep(700);
    c = await evaluate(session, CASE);
    trace.push(`#${seq}${label}→${c.steps[seq]}(${c.state.replace('状态 · ', '')})`);
  }
  suite.check(
    '② 逐步推进符合状态机，全部完成后档案变「待验证」',
    c.hasVerify && c.steps.length === 5 && c.steps.every((s) => s === '已完成'),
    `轨迹=${trace.join(' | ')}｜末次步骤=${c.steps.join(',')}｜状态=${c.state}`,
  );

  // ③ 验证入口
  const verifyBtns = await evaluate(session, `[...document.querySelectorAll('button')].map((b) => b.textContent.trim()).filter((t) => t.includes('归档') || t.includes('继续观察'))`);
  suite.check(
    '③ 「待验证」时提供验证输入与「归档 · 问题解决 / 继续观察」',
    c.hasVerify && verifyBtns.length >= 2,
    `验证输入=${c.hasVerify}｜按钮=${JSON.stringify(verifyBtns)}`,
  );

  // ④ 未填说明不能归档（不伪装成功）
  await clickByText(session, 'button', '归档 · 问题解决');
  await sleep(900);
  const afterEmpty = await evaluate(session, CASE);
  const emptyToast = (await toastLog(session)).filter((t) => String(t).includes('验证说明'));
  suite.check(
    '④ 未填验证说明点归档被拒（400 + 报错提示，状态仍「待验证」）—— 不伪装成功',
    afterEmpty.state.includes('待验证') && emptyToast.length >= 1,
    `状态=${afterEmpty.state}｜含「必须填写验证说明」的 toast=${JSON.stringify(emptyToast)}`,
  );

  // ⑤ 归档
  await typeInto(session, 'input[placeholder^="填写验证说明"]', VERIFY_NOTE);
  await clickByText(session, 'button', '归档 · 问题解决');
  await sleep(1000);
  c = await evaluate(session, CASE);
  suite.check(
    '⑤ 归档后档案「已归档」、archive 追加验证记录、步骤推进被冻结',
    c.state.includes('已归档') && c.archive.includes('resolved: ' + VERIFY_NOTE)
      && c.canStart === 0 && c.canDone === 0 && c.canBlock === 0 && !c.hasExpertAdd,
    `状态=${c.state}｜可推进=${c.canStart}/${c.canDone}/${c.canBlock}｜加专家入口=${c.hasExpertAdd}｜archive 末行=${JSON.stringify(c.archive.split('\n').pop() ?? '')}`,
  );
  await screenshot(session, 'demo-action-loop-resolved');


  // ⑥ 归档即入知识库（问题条目）
  await goto(session, url('#page=knowledge'), { waitSelector: '.page.active' });
  await sleep(800);
  let kb = await evaluate(session, KB);
  const problemEntry = kb.entries.find((e) => e.type === '问题');
  suite.check(
    '⑥ 归档即入库：知识库出现「问题」条目（PRF-0831，结论 = 验证说明）',
    !!problemEntry && problemEntry.meta.includes(CASE_NO) && problemEntry.note.includes(VERIFY_NOTE)
      && kb.filters.includes('问题（1）'),
    `计数=${JSON.stringify(kb.filters)}｜条目=${JSON.stringify(problemEntry ?? null)}`,
  );

  // ⑦ 沉淀经验（幂等）
  await goto(session, url('#page=action'), { waitSelector: '.timeline' });
  await sleep(800);
  await typeInto(session, 'input[placeholder^="沉淀结论"]', LESSON_NOTE);
  await clickByText(session, 'button', '沉淀经验');
  await sleep(1000);
  const learnedState = await evaluate(session, CASE);
  await goto(session, url('#page=knowledge'), { waitSelector: '.page.active' });
  await sleep(800);
  kb = await evaluate(session, KB);
  const lessonEntry = kb.entries.find((e) => e.type === '经验');
  suite.check(
    '⑦ 沉淀经验 → 知识库出现「经验」条目，且不重复计数',
    learnedState.learned && !!lessonEntry && lessonEntry.note.includes(LESSON_NOTE)
      && kb.filters.includes('经验（1）') && kb.filters.includes('全部（2）'),
    `已沉淀标记=${learnedState.learned}｜计数=${JSON.stringify(kb.filters)}｜条目=${JSON.stringify(lessonEntry ?? null)}`,
  );

  // ⑧ 整页刷新后状态保留（sessionStorage）
  await goto(session, url('#page=action'), { waitSelector: '.timeline' });
  await sleep(800);
  const c2 = await evaluate(session, CASE);
  await goto(session, url('#page=knowledge'), { waitSelector: '.page.active' });
  await sleep(700);
  const kb2 = await evaluate(session, KB);
  suite.check(
    '⑧ 整页刷新后状态保留（sessionStorage）：档案仍「已归档」、知识库仍 2 条',
    c2.state.includes('已归档') && kb2.filters.includes('全部（2）') && kb2.filters.includes('经验（1）'),
    `刷新后档案=${c2.state}｜知识库=${JSON.stringify(kb2.filters)}`,
  );

  // ⑨ 冻结语义（直接打接口，不经界面）
  const frozen = await evaluate(session, `fetch('/api/action/cases/p1/steps/0/start', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' }).then((r) => r.json().then((b) => r.status + '|' + (b.detail ?? '')))`);
  suite.check(
    '⑨ 已归档档案的推进接口如实 400（冻结，不伪装成功）',
    String(frozen).startsWith('400|') && String(frozen).includes('冻结'),
    `POST steps/0/start → ${frozen}`,
  );

  // ⑩ 清除数据 → 演示状态一并重置
  await clickByText(session, '.topbar .top-btn', '更新数据');
  await sleep(500);
  const modalOpen = await evaluate(session, `!!document.querySelector('.dsm-panel')`);
  await clickByText(session, '.dsm-danger button', '清除数据');
  const backToBoot = await visible(session, `!!document.querySelector('.boot-card')`, { timeout: 6000, label: '清除后回到数据入口页' });
  await screenshot(session, 'demo-clear-data-reset'); // 证据：清除数据后回到标注好的数据入口页
  const storeCleared = await evaluate(session, `(() => { try { return window.sessionStorage.getItem('doraDemoState.v1') === null; } catch (e) { return true; } })()`);
  await clickByText(session, 'button', '载入内置样例数据');
  const pulseBack = await visible(session, `!!document.querySelector('.priority-title')`, { timeout: 15000, label: '重新载入内置数据后回到脉搏' });
  await goto(session, url('#page=action'), { waitSelector: '.page.active' });
  await sleep(800);
  const actionBody = await bodyText(session);
  await goto(session, url('#page=knowledge'), { waitSelector: '.page.active' });
  await sleep(700);
  const kb3 = await evaluate(session, KB);
  suite.check(
    '⑩ 清除数据时演示状态一并重置（回入口页 + sessionStorage 清空 + 行动 0 份 + 知识库 0 条）',
    modalOpen && backToBoot && storeCleared && pulseBack
      && actionBody.includes('我的档案 0 份') && kb3.filters.includes('全部（0）'),
    `弹层=${modalOpen}｜回入口页=${backToBoot}｜存储已清=${storeCleared}｜重新载入=${pulseBack}｜行动空=${actionBody.includes('我的档案 0 份')}｜知识库=${JSON.stringify(kb3.filters)}`,
  );
} catch (err) {
  fatal(err);
}

await finish(suite, [server?.close, chrome?.close]);

