#!/usr/bin/env node
/**
 * 设计展示 demo：把前端打成「单文件 HTML」。
 *
 * 产物：frontend/design-demo/dora-design-demo.html（双击即可打开；不需要后端、不需要 node、不发任何网络请求）
 * 用法：cd frontend && npm run demo:html
 *
 * 默认（不设环境变量）= **初始状态**：`VITE_API_MODE=mock` 构建，页面只读 src/data.ts 的演示快照，
 * 行动回路保持离线演示（只渲染本机「加入」过的档案）。
 *
 * 可选：内联**真实行动档案快照**（change `demo-real-action-snapshot`，显式开启）
 *       DORA_DEMO_API=http://127.0.0.1:8010/api npm run demo:html   # 指向后端抓快照
 *
 * 为什么这么做：
 *   - 默认以 VITE_API_MODE=mock 构建 → 不向 /api 发请求（离线可演示）；
 *   - CSS / JS 全量内联 → 一个 html 即可演示全部页面（业务脉搏 / 洞察 / 行动 / 守护 / 知识）与抽屉、弹层交互；
 *   - 注入「演示引导」脚本：冷启动页标「演示模式 · 数据已内置」并**自动载入内置数据** → 首开即落在「业务脉搏」，评审不需要上传文件（见 BOOTSTRAP）。
 *
 * 开启快照时（`DORA_DEMO_API` 已设置；change `demo-real-action-snapshot` + 2026-09-26 收敛）：
 *   - 后端可达时抓：`GET /insights?type=all`（洞察）、**`GET /evidence/{洞察id}`（证据链，逐条）**、`GET /watch`（真实委托）、
 *     **`GET /knowledge` + `GET /action/lessons`（知识库初始数据）**、`GET /action/cases?origin=all` 与每份详情、
 *     `POST /datasets/sample`（样例载入）；默认先对每份档案的洞察 id 调 `POST /action/cases {claim:true}`（`DORA_DEMO_CLAIM=0` 关闭）；
 *   - **编号统一**：把该洞察对应的**案号**写进它唯一可显示的字段 `tag`（洞察页 / 脉搏卡只显示 tag），
 *     例：`PRF-0831 · 问题 · 高影响`；没有对应档案的洞察（如"变化"类 c1–c4）保持原样；
 *   - **初始只有洞察**：拦截器让 `/api/watch`、`/api/action/cases` 初始返回空 → 加载数据后没有任何行动与关注；
 *   - **升级才有行动/关注**：`POST /api/action/cases {insight_id}` 把快照里该洞察的**真实档案**（含步骤 / 专家）加入
 *     演示内状态并返回；`POST /api/watch` 支持在演示内存里创建「一句话委托」（明确标注未连接引擎）；
 *   - **演示内可走完行动回路**（迭代 70）：`steps/{seq}/start|done|blocked`、`steps/{seq}/experts`、`verify`、
 *     `archive-as-lesson` 在演示状态里实现**与后端 `app/action/flow.py` 同一契约**（全部完成 → 待验证 → 归档即按
 *     案件类型写入知识库；沉淀经验再写一条「经验」条目；非法迁移同样 400、resolved 冻结）；
 *   - 仍未覆盖的写操作（上传文件、委托检查/暂停/删除等）返回 409「只读演示」→ 页面如实提示，不伪装成功；
 *   - 产物**不发任何真实网络请求**；右下角常驻标注「真实数据快照 · <时间> · 非实时后端（升级/推进/归档在演示内生效）」。
 *
 * 注：产物是构建物，按仓库约定（同 dist）不入库，见 frontend/.gitignore。
 */
import { spawnSync } from 'node:child_process';
import { existsSync, mkdirSync, mkdtempSync, readdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const outFile = path.join(root, 'design-demo', 'dora-design-demo.html');
const stage = mkdtempSync(path.join(tmpdir(), 'dora-design-demo-'));

const DEMO_TITLE = 'Dora · AI 主动经营驾驶舱（设计演示 · 单文件离线版）';

/**
 * 演示引导：**首开即「标注好的演示页 + 自动载入内置数据」** —— 评审不需要上传任何文件。
 *
 * 2026-09-26 第二次收敛（用户：「这个页面标注好 demo，请直接载入内部数据，不要让自己上传，
 * 下面的小字没对上/不居中」）：
 *   ① 演示标注 + **隐藏上传入口**（单文件 demo 解析不了真实文件，拦截器对 `/api/datasets` 一律 409，
 *      留着「点击选择或拖入经营数据文件」只会误导评审）→ 由 `PANEL_CSS` 的 `.dora-demo` 规则做，不碰产品样式；
 *   ② 底部小字换成与演示一致的文案（原来写「后端在线：上传按…真实解析入库」，可 demo 里既没有上传、
 *      也没有后端），并整体居中，与整页居中的构图对齐；
 *   ③ 页面**自己点一次**「载入内置样例数据」（走的是应用自身的离线样例路径，不伪造数据）：
 *      首开 = 标注过的冷启动页（约 1.2s）→ 解析动画（约 1.9s）→ 业务脉搏，全程零操作。
 * 已在别处载入过数据（localStorage 记忆）时直接进脉搏；页内「更新数据 → 清除数据」仍会回到本页
 * （回到的也是这张标注好、无上传入口的演示页），并且**演示状态一并重置**：行动回路 / 持续关注 /
 * 知识库归档全部回到快照初始态（页面回到这里就是「没有数据源」的信号），清完停在本页等用户再点
 * 「载入内置样例数据」——下一位评审因此总能拿到干净起点。
 */
const BOOTSTRAP = `  <script>
    (function () {
      document.documentElement.classList.add('dora-demo');
      var NOTE = '演示模式：本页只展示冷启动形态；演示已内置门店经营数据.xlsx，无需上传文件，也不连接后端。';
      console.info('[design-demo] 单文件离线演示：冷启动页已标注「演示模式 · 数据已内置」，并会自动载入内置数据（不需要上传、不连后端）。');
      var patch = function () {
        if (!document.querySelector('.boot-card')) return; // 已离开冷启动页
        var note = document.querySelector('.boot-note > span:not(.tag)');
        if (note && note.textContent !== NOTE) note.textContent = NOTE;
      };
      var auto = function () {
        var b = document.querySelector('.up-sample');
        if (!b || b.dataset.doraDemoAuto) return;
        b.dataset.doraDemoAuto = '1';
        console.info('[design-demo] 自动载入内置数据（等价于点一次「载入内置样例数据」）。');
        b.click();
      };
      var start = function () {
        patch();
        new MutationObserver(patch).observe(document.documentElement, { childList: true, subtree: true, characterData: true });
        window.setTimeout(auto, 1200); // 留出时间让评审先看清这张标注过的冷启动页
      };
      if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start); else start();
    })();
  </script>
`;

/**
 * 真实行动档案快照（build-time）：后端可达时抓真接口，否则复用上次缓存。
 *
 * 为什么在构建期抓：demo 必须"双击即看、不发请求"（单文件），但又希望它的行动回路显示**真实**档案
 * （列表 / 详情 / 步骤 / 专家）→ 只能把真实响应在构建期固化进产物，再由只读拦截器喂给 Action 页。
 */
const API = (process.env.DORA_DEMO_API || 'http://127.0.0.1:8000/api').replace(/\/+$/, '');
const SNAPSHOT_CACHE = path.join(root, 'design-demo', 'action-snapshot.json');
const CLAIM = process.env.DORA_DEMO_CLAIM !== '0';

async function apiJson(pathname, init) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), 4000);
  try {
    const res = await fetch(`${API}${pathname}`, { ...init, signal: ctrl.signal });
    const body = await res.json().catch(() => null);
    if (!res.ok) throw new Error(`${(init && init.method) || 'GET'} ${pathname} → HTTP ${res.status}`);
    return body;
  } finally {
    clearTimeout(timer);
  }
}

async function captureSnapshot() {
  const cases = (await apiJson('/action/cases?origin=all'))?.cases ?? [];
  if (CLAIM) {
    // 让快照记录"用户已加入这 N 份"的真实状态（决策 3）：origin=mine 才会有内容
    for (const c of cases) {
      try {
        await apiJson('/action/cases', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ insight_id: c.id, claim: true }),
        });
      } catch (err) {
        console.log(`  · 跳过 claim ${c.code}：${err instanceof Error ? err.message : err}`);
      }
    }
  }
  const byOrigin = {};
  for (const origin of ['all', 'mine', 'demo']) {
    byOrigin[origin] = (await apiJson(`/action/cases?origin=${origin}`))?.cases ?? [];
  }
  const details = {};
  for (const c of cases) details[c.id] = (await apiJson(`/action/cases/${c.id}`))?.case ?? null;
  // 洞察 + 真实委托：供「初始只有洞察 → 升级才有行动/关注」与**编号统一**使用
  const insightsRaw = await apiJson('/insights?type=all');
  const watchRaw = await apiJson('/watch');
  // 编号统一：把该洞察对应的**案号**写进它唯一可显示的字段 `tag`（洞察页与脉搏卡只显示 tag）
  const codeById = new Map(cases.map((c) => [c.id, c.code]));
  const insights = (Array.isArray(insightsRaw) ? insightsRaw : []).map((i) => (
    codeById.has(i.id) ? { ...i, tag: `${codeById.get(i.id)} · ${i.tag}` } : i
  ));
  const watch = Array.isArray(watchRaw) ? watchRaw : [];
  // 知识 / 归档库 + 经验列表：demo 里「走完回路 → 归档 → 沉淀经验」会把新条目加在这份**真实初始列表**之上，
  //   所以知识库页面一开始就显示真数据（本机演示库当前为空 → 如实显示空态，直到演示内归档）。
  let knowledge = [];
  let lessons = [];
  try {
    knowledge = (await apiJson('/knowledge'))?.entries ?? [];
    lessons = (await apiJson('/action/lessons'))?.lessons ?? [];
  } catch (err) {
    console.log(`  · 知识/经验快照不可用（${err instanceof Error ? err.message : err}）→ 以空列表开始`);
  }
  // 证据链：洞察详情 / 脉搏问题卡 / 行动步骤的「打开证据链」都走 `GET /api/evidence/{id}`，
  //   快照必须一起抓 —— 否则 demo 跑在 auto 模式时（拦截器让 `/insights` 成功 → `source=live`），
  //   这些按钮只会拿到「证据读取失败」（P041）。抓不到的那条**如实不写入**，运行期按 404 暴露。
  const evidence = {};
  for (const i of insights) {
    try {
      const ev = await apiJson(`/evidence/${i.id}`);
      if (ev) evidence[i.id] = ev;
    } catch (err) {
      console.log(`  · 跳过 ${i.id} 的证据链：${err instanceof Error ? err.message : err}`);
    }
  }
  // 样例数据载入（demo 首开停在「数据入口」页，用户点「载入内置样例数据」会走这里）：
  //   真后端响应；取不到时用**应用自身的离线形态**（`{ok:true,counts:{},offline:true}`，不伪造解析结果）
  let sample;
  try {
    sample = await apiJson('/datasets/sample', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: '{}',
    });
  } catch (err) {
    console.log(`  · 样例载入接口不可用（${err instanceof Error ? err.message : err}）→ 用应用离线形态 { ok:true, counts:{}, offline:true }`);
    sample = { ok: true, counts: {}, offline: true };
  }
  return {
    fetchedAt: new Date().toISOString().slice(0, 16).replace('T', ' '),
    apiBase: API,
    claimed: CLAIM,
    byOrigin,
    details,
    insights,
    evidence,
    watch,
    knowledge,
    lessons,
    sample,
  };
}

async function loadSnapshot() {
  try {
    const snap = await captureSnapshot();
    mkdirSync(path.dirname(SNAPSHOT_CACHE), { recursive: true });
    writeFileSync(SNAPSHOT_CACHE, JSON.stringify(snap));
    console.log(`· 真实行动档案快照：${snap.byOrigin.all.length} 份（${CLAIM ? '含 claim' : '未 claim'}）· ${snap.fetchedAt} · 来源 ${API}`);
    console.log(`  · 证据链快照：${Object.keys(snap.evidence).length}/${snap.insights.length} 条洞察（缺的那条在演示里会如实 404）`);
    console.log(`  · 知识库快照：${(snap.knowledge || []).length} 条知识 / ${(snap.lessons || []).length} 条经验（演示内归档会叠加在这之上）`);
    return snap;
  } catch (err) {
    const reason = err instanceof Error ? err.message : String(err);
    if (existsSync(SNAPSHOT_CACHE)) {
      const snap = JSON.parse(readFileSync(SNAPSHOT_CACHE, 'utf8'));
      const n = snap.byOrigin && snap.byOrigin.all ? snap.byOrigin.all.length : 0;
      const evN = snap.evidence ? Object.keys(snap.evidence).length : 0;
      console.log(`· 后端不可达（${reason}）→ 复用缓存快照：${n} 份 · ${snap.fetchedAt} · 证据链 ${evN} 条`);
      // 旧缓存（本字段是 2026-09-26 才加的）没有证据链 → 演示里「打开证据链」会如实 404。
      // 不静默：明确提示重建方式（用户点不动按钮时最需要知道的就是这句）。
      if (!evN) {
        console.log('  ⚠ 缓存快照不含证据链（旧版本产物）→ 演示里「打开证据链」会报「演示快照未包含该洞察的证据链」。');
        console.log('    补全方式：后端在线时重建 → DORA_DEMO_API=http://127.0.0.1:8010/api npm run demo:html');
      }
      return snap;
    }
    console.log(`· 后端不可达（${reason}）且无缓存快照 → 本次产物不含真实档案快照（行动回路保持离线演示）`);
    return null;
  }
}

/**
 * 脉搏页三块面板：左卡固定高度 + 只有它一层滚动；右列两卡**按内容高度排布、不滚动**
 * （**demo 覆盖样式**，产品样式不动）。
 *
 * 迭代 65（用户实测反馈「布局不好看」）：① 行内「证据 / 证据链」贴着行左边与下边（原样式只给了
 * `padding:9px 0 0`，那 12px 内缩本该由 `.problem-body` 提供，而这份标记是直接挂在 `.problem-item`
 * 下的）→ 补 `9px 12px 12px`；② 右列原来是「各占一半 294px + 内滚」，监控状态卡下方留下 77px 空档、
 * 「本轮工作」被压到必须滚动 → 改为**贴合内容**（实测 217 + 348 + 12 间距 = 577 ≤ 左卡 600），
 * 监控状态下边界上移、本轮工作上边界随之上移，两块都不用滚动。
 *
 * 迭代 66（用户实测反馈「把左边板块下边界往上一点，确保左右对齐」）：左卡此前**写死 600px**，
 * 而右列是内容高度 577 → 左卡底边比右列低 23px，写死值也永远追不上内容高度。
 * 改为**让右列决定这一行的高度、左卡自己撑满**：左卡 `contain:size`（自身内容不参与行高计算）+
 * 默认 `align-self:stretch` → 行高 = 右列内容高（现 577），两者底边天然齐平；
 * 内容超出仍由左卡外层滚动。高度从此没有魔法数字，右列内容变长/变短时两边始终对齐。
 */
const PANEL_CSS = `  <style>
    /* 洞察详情「事实 · 具体数据」：整组事实收进一个**会随行高伸缩的量测面板**，关键数值升级为 hero 大数字。
       右栏（判断）内容更长时，多出来的高度落进面板内边距（= 有意的呼吸），而不是在卡片底部留一块空洞；
       面板底色跟随洞察类型（问题红 / 机会绿 / 变化蓝），:has() 不可用时退回中性淡紫，不影响可读性。
       注意：本段不按宽度分档 —— 窄屏（单列）下 flex:1 不生效，面板即内容高度，同样成立。 */
    .judge-facts .ev-list{flex:1 1 auto;justify-content:center;gap:7px;background:#f7f6ff;border:1px solid #e7e4ff;border-radius:12px;padding:16px 15px}
    .judge-facts .ev-row:first-child{display:flex;flex-direction:column;gap:3px}
    .judge-facts .ev-row:first-child b{flex:none;font-size:11px}
    .judge-facts .ev-row:first-child span{font-size:40px;font-weight:900;line-height:1.05;letter-spacing:-.8px;color:#242938}
    .judge-facts .ev-list>.ev-row:nth-child(2){border-top:1px dashed rgba(120,116,170,.3);padding-top:7px}
    .judge-facts .cause-item{padding:12px 13px;gap:3px}
    .judge-facts .cause-item b{font-size:14px}
    .judge-facts .cause-item em{font-size:24px;line-height:1.15}
    .card.detail:has(> .detail-top > div:first-child > .tag.red) .judge-facts .ev-list{background:var(--red-soft);border-color:#ffdce1}
    .card.detail:has(> .detail-top > div:first-child > .tag.green) .judge-facts .ev-list{background:var(--green-soft);border-color:#d9f1e6}
    .card.detail:has(> .detail-top > div:first-child > .tag.blue) .judge-facts .ev-list{background:var(--blue-soft);border-color:#d9e5ff}
    /* 冷启动「数据入口」页（demo 覆盖，不按宽度分档；产品样式一行未动）：
       ① 标题行加「演示模式 · 数据已内置」标注 —— 用 ::after 而不是改 DOM，React 重渲染也不会掉；
       ② 隐藏上传入口：单文件 demo 解析不了真实文件（拦截器对 /api/datasets 一律 409），
          留着「点击选择或拖入经营数据文件」只会让评审以为要自己上传 → 只留「载入内置样例数据」一个动作；
       ③ 底部小字由引导脚本换成演示文案，这里把它整体居中并与标签垂直居中对齐
          （原来贴着左下、单行拉满卡宽，与整页居中的构图对不上）。 */
    .dora-demo .boot-head .eyebrow{display:flex;align-items:center;gap:8px}
    .dora-demo .boot-head .eyebrow::after{content:'演示模式 · 数据已内置';font-size:10px;letter-spacing:.06em;color:#5b54c6;background:#f1f0ff;border:1px solid #ddd9ff;border-radius:999px;padding:3px 9px}
    .dora-demo .up-drop,.dora-demo .up-or{display:none}
    .dora-demo .up-sample{margin-top:0}
    .dora-demo .boot-note{justify-content:center;align-items:center;text-align:center;gap:8px;max-width:620px;margin:18px auto 0;flex-wrap:wrap}
    .dora-demo .boot-note .tag{margin-top:0}
    @media (min-width:1251px){
      /* 行高**只由右列内容决定**，左右两列都撑满这一行 → 底边天然对齐 */
      .pulse-layout{align-items:stretch}
      /* 左：今日经营主线 + 业务脉络·问题 —— 高度跟着右列走（contain:size 让自身内容不参与行高计算，
         否则它会按 904px 的内容高度把这行撑高），**只有卡片这一层（外层）滚动**；
         卡片内内容**完整展示**（问题列表不再单独滚动、行与其它子元素一律不压缩）。
         红边条改用 border-left：原来靠绝对定位伪元素，卡片滚动时会跟着内容错位 */
      .pulse-priority{contain:size;align-self:stretch;height:auto;display:flex;flex-direction:column;overflow-y:auto;border-left:4px solid var(--red)}
      .pulse-priority::before{display:none}
      .pulse-priority>*{flex:0 0 auto}
      .pulse-priority .problem-stack{display:flex;flex-direction:column}
      .pulse-priority .problem-stack-head{flex:0 0 auto}
      .pulse-priority .problem-list{flex:0 0 auto;height:auto;min-height:0;max-height:none;overflow-y:visible;padding-right:0}
      .pulse-priority .problem-list>.problem-item{flex:0 0 auto}
      /* 行内「证据 / 证据链」：补 12px 内缩 + 12px 下留白，别贴着行的左边与下边（行高 124 → 136） */
      .pulse-priority .problem-evidence{padding:9px 12px 12px}
      /* 右：Dora 监控状态 / 本轮 Dora 工作 —— **按内容高度排布、不拉伸也不滚动**（预计 217 + 348 ≤ 左卡 600） */
      .cockpit-side{height:auto}
      .cockpit-side .monitor-card{flex:0 0 auto;overflow:visible}
      /* 左卡是页面上唯一的滚动面板：细滚动条 */
      .pulse-priority{scrollbar-width:thin;scrollbar-color:#c9c6f5 transparent;overscroll-behavior:contain}
      .pulse-priority::-webkit-scrollbar{width:7px}
      .pulse-priority::-webkit-scrollbar-thumb{background:#c9c6f5;border-radius:8px}
      .pulse-priority::-webkit-scrollbar-track{background:#f0f1f6;border-radius:8px}
    }
  </style>
`;

/** 快照拦截器（演示内状态机）+ 常驻标注：洞察 / 关注 / 行动档案都走快照，初始只有洞察。 */
const snapshotScripts = (snap) => {
  if (!snap) return '';
  const data = `  <script>window.__DORA_DEMO_SNAPSHOT__ = ${JSON.stringify(snap).replace(/</g, '\\u003c')};</script>\n`;
  const shim = `  <script>
    (function () {
      var snap = window.__DORA_DEMO_SNAPSHOT__;
      if (!snap) return;
      var badge = document.createElement('div');
      badge.className = 'demo-snapshot-badge';
      badge.textContent = '真实数据快照 · ' + snap.fetchedAt + ' · 非实时后端（升级/推进/归档在演示内生效）';
      badge.style.cssText = 'position:fixed;right:12px;bottom:12px;z-index:9999;background:rgba(23,25,35,.86);color:#fff;font-size:11px;padding:5px 9px;border-radius:999px;pointer-events:none';
      var mount = function () { if (document.body) document.body.appendChild(badge); };
      if (document.body) mount(); else document.addEventListener('DOMContentLoaded', mount);
      var reply = function (obj, status) {
        return Promise.resolve(new Response(JSON.stringify(obj), { status: status, headers: { 'Content-Type': 'application/json' } }));
      };
      // 演示内状态：**初始没有任何行动档案与持续关注**；只有洞察（快照里的真实洞察，tag 已含案号）。
      // 行动回路可在演示内**走完**（开始/完成/受阻 → 全部完成变「待验证」→ 验证归档 → 沉淀经验 → 知识库），
      // 状态机与后端 app/action/flow.py 同一契约（非法迁移同样 400，不伪装成功）。
      // 状态存 sessionStorage：刷新页面保留、关掉标签页/换新标签即回到快照初始态。
      var STORE = 'doraDemoState.v1';
      var seed = {
        cases: [], watch: [],
        lessons: (snap.lessons || []).slice(),
        knowledge: (snap.knowledge || []).slice(),
        kid: 0,
      };
      var state = seed;
      var loadState = function () {
        try {
          var raw = window.sessionStorage.getItem(STORE);
          if (!raw) return seed;
          var saved = JSON.parse(raw) || {};
          return {
            cases: saved.cases || [], watch: saved.watch || [],
            lessons: saved.lessons || seed.lessons,
            knowledge: saved.knowledge || seed.knowledge,
            kid: saved.kid || 0,
          };
        } catch (e) { return seed; }   // 隐私模式 / 禁用存储：退化为内存态
      };
      var saveState = function () {
        try { window.sessionStorage.setItem(STORE, JSON.stringify(state)); } catch (e) { /* 同上：退化为内存态 */ }
      };
      state = loadState();
      // 「清除数据」＝ 冷启动页重新出现（该页只在没有数据源时渲染）→ 演示里那套状态
      // （行动回路 / 持续关注 / 知识库归档）必须**一起清掉**：否则清完数据还留着上一位评审
      // 归档的档案与经验，下一位评审拿到的就不是干净起点。每次进入这一页只清一次。
      // 注意：这段必须在 shim 里（state / snap 在 shim 的作用域），BOOTSTRAP 那个 script 看不到它们。
      var onBoot = false;
      var watchClear = function () {
        if (!document.querySelector('.boot-card')) { onBoot = false; return; }
        if (onBoot) return;
        onBoot = true;
        var seeded = (snap.knowledge || []).length + (snap.lessons || []).length;
        var had = state.cases.length + state.watch.length + state.knowledge.length + state.lessons.length > seeded;
        state = {
          cases: [], watch: [],
          lessons: (snap.lessons || []).slice(),
          knowledge: (snap.knowledge || []).slice(),
          kid: 0,
        };
        try { window.sessionStorage.removeItem(STORE); } catch (e) { /* 退化内存态 */ }
        if (had) console.info('[design-demo] 已随「清除数据」重置演示状态：行动回路 / 持续关注 / 知识库回到快照初始态。');
      };
      new MutationObserver(watchClear).observe(document.documentElement, { childList: true, subtree: true });
      watchClear();
      var parseBody = function (init) { try { return JSON.parse((init && init.body) || '{}') || {}; } catch (e) { return {}; } };
      window.fetch = function (input, init) {
        var url = typeof input === 'string' ? input : (input && input.url) || '';
        var method = ((init && init.method) || (input && input.method) || 'GET').toUpperCase();
        // 冷启动「数据入口」页要用的样例载入：用快照里的真实响应放行（否则用户点不动）
        if (url.indexOf('/api/datasets/sample') !== -1) {
          return reply(snap.sample || { ok: true, counts: {}, offline: true }, 200);
        }
        // 上传路径：单文件 demo 无法真解析文件 → 明确拒绝，不伪造解析结果
        if (url.indexOf('/api/datasets') !== -1) {
          return reply({ detail: '离线演示不能上传真实文件，请先连接后端' }, 409);
        }
        // 洞察：快照里的真实洞察（tag 里带统一案号），只读
        if (url.indexOf('/api/insights') !== -1) {
          if (method !== 'GET') return reply({ detail: '演示快照：这是只读演示，写操作不会落库' }, 409);
          var t = (url.match(/type=([a-z]+)/) || [])[1] || 'problem';
          var ins = (!t || t === 'all') ? (snap.insights || []) : (snap.insights || []).filter(function (i) { return i.type === t; });
          return reply(ins, 200);
        }
        // 证据链：快照里的**真实**证据（洞察详情 / 脉搏问题卡 / 行动步骤的「打开证据链」都读它）。
        // 缺失时如实 404（与后端同形状）并指出补救办法，不伪造证据。
        if (url.indexOf('/api/evidence/') !== -1) {
          var eid = url.split('/api/evidence/')[1].split('?')[0].split('#')[0];
          var ev = (snap.evidence || {})[eid];
          return ev ? reply(ev, 200) : reply({ detail: '演示快照未包含该洞察的证据链（后端在线时重建 demo 可补全）' }, 404);
        }
        // 持续关注：初始为空；支持在演示内存里创建「一句话委托」（真实引擎评估不可用）
        if (url.indexOf('/api/watch') !== -1) {
          if (url.indexOf('/api/watch/parse') !== -1) {
            return reply({ detail: '演示：委托解析走前端内置演示解析' }, 409);
          }
          var wid = url.indexOf('/api/watch/') !== -1 ? url.split('/api/watch/')[1].split('?')[0].split('#')[0] : '';
          if (method === 'GET') {
            if (wid) {
              var w1 = state.watch.filter(function (w) { return w.id === wid; })[0];
              return w1 ? reply(w1, 200) : reply({ detail: '演示态中无此委托' }, 404);
            }
            return reply(state.watch, 200);
          }
          if (method === 'POST' && !wid) {
            var wb = parseBody(init);
            var text = String(wb.text || '').slice(0, 40);
            var card = { id: 'demo' + (state.watch.length + 1), name: text || '新委托', value: '—', color: 'blue', logic: '演示态：未连接引擎，不做真实评估', source: '演示（本机）' };
            state.watch.push(card);
            saveState();
            return reply({ ok: true, target: card }, 200);
          }
          return reply({ detail: '演示快照：这是只读演示，写操作不会落库' }, 409);
        }
        // 行动档案：初始为空；「加入行动回路」把快照里该洞察的**真实档案**（含步骤/专家）加入演示状态。
        // 之后可在演示内**走完回路**：开始/完成/受阻（含「全部完成 → 待验证」）→ 验证归档 → 沉淀经验。
        // 状态机语义照抄后端 app/action/flow.py：非法迁移 400、resolved 冻结、归档与知识入库同一步。
        if (url.indexOf('/api/action/cases') !== -1) {
          var rest = url.indexOf('/api/action/cases/') !== -1 ? url.split('/api/action/cases/')[1].split('?')[0].split('#')[0] : '';
          var seg = rest ? rest.split('/') : [];
          var cid = seg[0] || '';
          var tail = seg.slice(1).join('/');
          var body = parseBody(init);
          var now = new Date().toISOString();
          var findBy = function (id) { return state.cases.filter(function (x) { return x.id === id; })[0]; };
          var stepOf = function (c, seq) { return (c.steps || []).filter(function (x) { return x.seq === seq; })[0]; };
          // 全 done → waiting_verify，否则 running（= flow.py 的 _recompute_case_status）
          var recompute = function (c) {
            var sts = (c.steps || []).map(function (x) { return x.status; });
            c.status = (sts.length && sts.every(function (x) { return x === 'done'; })) ? 'waiting_verify' : 'running';
          };
          // 知识入库：按 (entry_type, source_id) 幂等（= repository 的同一约束）
          var pushKnowledge = function (entryType, sourceId, code, title, content, note) {
            var has = state.knowledge.some(function (e) { return e.entry_type === entryType && e.source_id === sourceId; });
            if (has) return false;
            state.kid += 1;
            state.knowledge.unshift({ id: 'demo-k' + state.kid, entry_type: entryType, source_id: sourceId, code: code, title: title, content: content, note: note, created_at: now });
            return true;
          };
          if (method === 'GET') {
            if (cid) {
              var one = findBy(cid);
              return one ? reply({ ok: true, case: one }, 200) : reply({ detail: '演示态中无此档案（先升级对应洞察）' }, 404);
            }
            var origin = (url.match(/origin=([a-z]+)/) || [])[1] || 'all';
            var cases = origin === 'all' ? state.cases : state.cases.filter(function (c) { return c.origin === origin; });
            return reply({ ok: true, cases: cases }, 200);
          }
          // ---- 写操作①：加入行动回路（把快照里的真实档案加入演示状态，按洞察 id 幂等） ----
          if (!cid) {
            var iid = body.insight_id || '';
            var detail = (snap.details || {})[iid];
            if (!detail) return reply({ detail: '演示快照中没有该洞察对应的行动档案' }, 404);
            var mine = findBy(iid);
            var created = false;
            if (!mine) {
              // 深拷贝：演示内的推进不能改到快照对象本身
              mine = Object.assign({}, detail, { origin: 'mine' });
              mine.steps = (detail.steps || []).map(function (s) {
                return Object.assign({}, s, { experts: (s.experts || []).slice() });
              });
              state.cases.push(mine);
              created = true;
              saveState();
            }
            return reply({ ok: true, created: created, case: mine }, 200);
          }
          var c = findBy(cid);
          if (!c) return reply({ detail: '演示态中无此档案（先升级对应洞察）' }, 404);
          // ---- 写操作②：验证归档 / 继续观察 ----
          if (tail === 'verify') {
            if (c.status === 'resolved') return reply({ detail: '演示态：档案已归档（resolved），不可重复验证' }, 400);
            if (body.outcome !== 'resolved' && body.outcome !== 'continue') return reply({ detail: 'invalid verify outcome: ' + body.outcome }, 400);
            var vnote = String(body.note || '');
            if (body.outcome === 'resolved') {
              var allDone = (c.steps || []).length > 0 && (c.steps || []).every(function (x) { return x.status === 'done'; });
              if (!allDone) return reply({ detail: 'resolved requires all steps done (case should be waiting_verify)' }, 400);
              if (!vnote.trim()) return reply({ detail: '归档（resolved）必须填写验证说明' }, 400);
              c.status = 'resolved';
              c.archive = (c.archive || '') + '\\n[' + now + '] resolved: ' + vnote;
              pushKnowledge(c.kind, c.id, c.code, c.case_title, c.archive, vnote);  // 与后端一致：归档即按案件类型入库
            } else {
              c.status = 'running';
              if (vnote) c.archive = (c.archive || '') + '\\n[' + now + '] continue: ' + vnote;
            }
            c.updated_at = now;
            saveState();
            return reply({ ok: true, case: c }, 200);
          }
          // ---- 写操作③：沉淀经验（resolved 档案 → 经验 + 知识库「经验」条目，按 case_id 幂等） ----
          if (tail === 'archive-as-lesson') {
            if (c.status !== 'resolved') return reply({ detail: '仅已归档（resolved）档案可沉淀经验' }, 400);
            var lnote = String(body.note || '');
            if (!lnote.trim()) return reply({ detail: '沉淀经验必须填写结论（note）' }, 400);
            var lesson = state.lessons.filter(function (l) { return l.case_id === c.id; })[0];
            var createdLesson = false;
            if (!lesson) {
              lesson = { case_id: c.id, code: c.code, kind: c.kind, title: c.case_title, archive: c.archive, resolution: lnote.trim(), created_at: now };
              state.lessons.unshift(lesson);
              createdLesson = true;
            }
            pushKnowledge('lesson', c.id, c.code, c.case_title, c.archive, lnote.trim());
            saveState();
            return reply({ ok: true, created: createdLesson, lesson: lesson }, 200);
          }
          // ---- 写操作④：单步推进 / 负责专家（resolved 冻结） ----
          // 注意：这里**不用正则**匹配 steps/2/done —— 模板字符串会把反斜杠转义吞掉（P037/P039 同族），
          // 拼出来的正则会让注入脚本语法错误（构建期自检会直接拦下）。用字符串切分最稳。
          var tseg = tail ? tail.split('/') : [];
          if (tseg.length === 3 && tseg[0] === 'steps' && /^[0-9]+$/.test(tseg[1])
            && ['start', 'done', 'blocked', 'experts'].indexOf(tseg[2]) !== -1) {
            if (c.status === 'resolved') return reply({ detail: '演示态：档案已归档（resolved），推进与专家设置已冻结' }, 400);
            var seq = Number(tseg[1]);
            var action = tseg[2];
            var st = stepOf(c, seq);
            if (!st) return reply({ detail: 'action step not found: seq=' + seq }, 400);
            if (action === 'experts') {
              var raw = Array.isArray(body.experts) ? body.experts : [];
              for (var i = 0; i < raw.length; i += 1) {
                if (typeof raw[i] !== 'string' || !raw[i].trim()) return reply({ detail: 'experts must be non-empty strings' }, 400);
              }
              var uniq = [];
              raw.forEach(function (n) { var v = n.trim(); if (uniq.indexOf(v) === -1) uniq.push(v); });
              if (uniq.length > 8) return reply({ detail: 'too many experts: ' + uniq.length + ' > 8' }, 400);
              st.experts = uniq;
              saveState();
              return reply({ ok: true, case: c }, 200);
            }
            if (action === 'start') {
              if (st.status !== 'pending' && st.status !== 'blocked') return reply({ detail: 'step ' + seq + ' can only start from pending|blocked, got ' + st.status }, 400);
              st.status = 'in_progress';
              c.status = 'running';
            } else if (action === 'blocked') {
              if (st.status !== 'in_progress') return reply({ detail: 'step ' + seq + ' can only be blocked from in_progress, got ' + st.status }, 400);
              st.status = 'blocked';
              st.note = String(body.note || '');
              c.status = 'running';
            } else {
              if (st.status !== 'in_progress') return reply({ detail: 'step ' + seq + ' can only be done from in_progress, got ' + st.status }, 400);
              st.status = 'done';
              st.note = String(body.note || '');
              st.result = String(body.result || '');
              recompute(c);
            }
            c.updated_at = now;
            saveState();
            return reply({ ok: true, case: c }, 200);
          }
          return reply({ detail: '演示快照：这是只读演示，写操作不会落库' }, 409);
        }
        // 知识 / 归档库：快照里已有的（构建期真数据）＋ 演示内归档新增的；type 过滤 + stats 同后端。
        // 注意**不**接管 /api/knowledge/search（检索走 watch 工作台，缺服务时页面如实提示不可用）。
        if (url.indexOf('/api/knowledge') !== -1 && url.indexOf('/api/knowledge/search') === -1) {
          var kt = (url.match(/type=([a-z]+)/) || [])[1] || '';
          var stats = { problem: 0, opportunity: 0, change: 0, lesson: 0 };
          state.knowledge.forEach(function (e) { if (typeof stats[e.entry_type] === 'number') stats[e.entry_type] += 1; });
          var entries = kt ? state.knowledge.filter(function (e) { return e.entry_type === kt; }) : state.knowledge;
          return reply({ ok: true, type: kt || 'all', entries: entries, stats: stats }, 200);
        }
        // 经验列表（/api/action/lessons）：快照初始 + 演示内沉淀
        if (url.indexOf('/api/action/lessons') !== -1) {
          return reply({ ok: true, lessons: state.lessons }, 200);
        }
        // 其余一律不触网：按网络失败处理 → 页面沿用既有离线回退（不伪造、不请求）
        return Promise.reject(new TypeError('Failed to fetch（design-demo 快照模式：未覆盖的接口按离线回退）'));
      };
      console.info('[design-demo] 洞察 / 证据链 / 行动档案 / 知识库来自构建期真实快照 · ' + snap.fetchedAt + '；初始只有洞察，升级后可走完行动回路（推进 → 归档 → 沉淀经验 → 知识库），状态存在本标签页（关掉即重置）。');
    })();
  </script>
`;
  return data + shim;
};


try {
  const snap = await loadSnapshot();
  // 有快照 → auto + 拦截器（拦截器接管**所有**请求，不会漏到真实网络）；
  // 无快照 → 保持 mock（与今天完全一致）。
  // 注意（P036）：无快照时若用 auto，被静态服务器托管的 demo 会把写操作打到 `/api/*` 收到 **HTTP 404**，
  // 而 404 不是"连接层失败" → 离线诚实路径（本机落账 + 未确认建档）不会触发，join 会直接失败。
  const mode = snap ? 'auto' : 'mock';
  console.log(`· vite build（VITE_API_MODE=${mode}${snap ? ' + 快照拦截（洞察/证据链/档案/知识库都走快照；初始只有洞察，升级后可走完行动回路并归档）' : '：无快照，离线演示数据'}）`);
  const built = spawnSync(
    path.join(root, 'node_modules', '.bin', 'vite'),
    ['build', '--outDir', stage, '--emptyOutDir', '--logLevel', 'warn'],
    { cwd: root, env: { ...process.env, VITE_API_MODE: mode }, stdio: 'inherit' },
  );
  if (built.status !== 0) throw new Error(`vite build 失败（exit ${built.status}）`);

  const assets = readdirSync(path.join(stage, 'assets'));
  const cssFile = assets.find((f) => f.endsWith('.css'));
  const jsFile = assets.find((f) => f.endsWith('.js'));
  if (!cssFile || !jsFile) throw new Error(`构建产物缺少 css/js：${assets.join(', ') || '(assets 为空)'}`);

  const css = readFileSync(path.join(stage, 'assets', cssFile), 'utf8');
  const js = readFileSync(path.join(stage, 'assets', jsFile), 'utf8');
  if (css.includes('</style')) throw new Error('CSS 含 </style，无法内联');

  // 内联 JS 必须切断 </script（浏览器遇到会提前闭合脚本标签）
  const safeJs = js.replace(/<\/script/gi, '<\\/script');

  const shell = readFileSync(path.join(stage, 'index.html'), 'utf8')
    .replace(/<title>[\s\S]*?<\/title>/, () => `<title>${DEMO_TITLE}</title>`)
    .replace(/<link[^>]*rel="modulepreload"[^>]*>\s*/g, '');

  // 外链自检必须在「内联前」做：内联后的 JS 里含 React 自身的 src/href 字面量（以及 Vite 嵌入的
  // html 模板字符串），检查全文会把自检变成误报。这里先摘掉两个待内联标签，只校验页面骨架。
  const bare = shell
    .replace(/<link[^>]*\.css[^>]*>/, '')
    .replace(/<script[^>]*type="module"[^>]*><\/script>/, '');
  if (bare === shell) throw new Error('内联替换未命中模板（index.html 结构已变，检查 css/script 标签）');
  if (bare.includes('/assets/') || bare.includes('src="') || bare.includes('href="')) {
    throw new Error('页面骨架仍存在外链资源引用，单文件在 file:// 下会白屏');
  }

  const moduleBlock = `${BOOTSTRAP}${snapshotScripts(snap)}  <script type="module">\n${safeJs}\n  </script>`;
  const styleBlock = `<style>\n${css}\n</style>`;

  // ⚠ 必须用「替换函数」而不是替换串：String.replace 的替换串里 $& / $' / $1 有特殊含义，
  //   而 JS 内容含 React 的 escapeUserProvidedKey（替换串写作 '$&/'）等 $ 序列——用替换串会被
  //   反向展开成「被匹配到的 <script ...> 标签」，在内联后注入裸 </script> 让脚本标签提前闭合 → 白屏。
  const out = shell
    .replace(/<link[^>]*\.css[^>]*>/, () => styleBlock + PANEL_CSS)
    .replace(/<script[^>]*type="module"[^>]*><\/script>/, () => moduleBlock);

  // 反向自检 1：内联必须逐字插入（若被 $ 序列展开，原文匹配不上）
  if (!out.includes(moduleBlock)) throw new Error('JS 未逐字内联（替换串被 $& / $1 等序列展开）');
  if (!out.includes(styleBlock)) throw new Error('CSS 未逐字内联');
  // 反向自检 2：全文只允许「引导 + module」两个裸 </script（接入真实快照时再加「数据 + 拦截器」两个）
  const expectedClosers = snap ? 4 : 2;
  const rawClosers = out.split('</script').length - 1;
  if (rawClosers !== expectedClosers) throw new Error(`脚本标签边界异常：裸 </script x${rawClosers}（应为 ${expectedClosers}）`);

  // 反向自检 3：注入的脚本必须能通过语法检查
  // （模板字符串里的转义很容易被吞掉 —— 曾把 `\/` 变成 `/`，让 // 变成注释、整个拦截器失效；见 P037）
  for (const [name, code] of [['BOOTSTRAP', BOOTSTRAP], ['snapshotScripts', snapshotScripts(snap)]]) {
    if (!code) continue;
    try {
      new Function(code.replace(/<\/?script[^>]*>/g, ''));
    } catch (err) {
      throw new Error(`注入脚本语法错误（${name}）：${err instanceof Error ? err.message : err}`);
    }
  }

  mkdirSync(path.dirname(outFile), { recursive: true });
  writeFileSync(outFile, out);
  const kb = (Buffer.byteLength(out) / 1024).toFixed(0);
  console.log(`✓ 单文件设计演示已生成：${path.relative(root, outFile)}（${kb} KB，自包含无外链）`);
  console.log(`  快照：${snap ? `洞察 ${snap.insights.length} 条（tag 含统一案号）· 证据链 ${Object.keys(snap.evidence || {}).length} 条 · 知识库 ${(snap.knowledge || []).length} 条 · 行动档案池 ${snap.byOrigin.all.length} 份 · ${snap.fetchedAt}；初始只有洞察，升级后可走完行动回路（推进 → 归档 → 沉淀经验 → 知识库）` : '未含快照（#page=action 保持离线演示）'}`);
  console.log('  打开方式：双击该文件；或 cd frontend/design-demo && python3 -m http.server 8080');
  console.log('  深链示例：#page=pulse | #page=insight&type=problem&idx=0 | #page=action | #page=watch | #page=knowledge');
  console.log('  首开状态：标注好的「数据入口」演示页（无上传入口）→ 自动载入内置数据 → 业务脉搏 / 洞察（无需点击）');
} catch (err) {
  console.error(`✗ 生成失败：${err instanceof Error ? err.message : err}`);
  process.exitCode = 1;
} finally {
  rmSync(stage, { recursive: true, force: true });
}
