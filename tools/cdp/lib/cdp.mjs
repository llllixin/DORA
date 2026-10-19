/**
 * Dora CDP 回归工具库（零依赖：Node ≥18 全局 WebSocket + 真实 Chrome）。
 *
 * 为什么在仓库里：迭代 43–53 的行为断言脚本原先都写在 `/tmp`，2026-09-13 收尾实测 `/tmp` 已清零
 * （`ls /tmp | grep -c dora` = 0），docs/openspec 里 27 处 `/tmp/*.mjs` 证据从此不可复现 → 落仓固化。
 *
 * 设计取舍：
 *   - 不用 puppeteer/playwright（新依赖 + 版本漂移）；直接说 CDP 协议（Chrome 111+ 建页要 PUT）。
 *   - 每个用例独立 Chrome profile + 独立静态端口 → 用例之间零状态串扰（P020：门禁必须幂等）。
 *   - toast 断言一律读「历史」（`window.__toastLog`，由 `Page.addScriptToEvaluateOnNewDocument`
 *     在页面脚本前安装）而不是读当下快照 —— 单槽 toast 会被后继通知抢占（P029）。
 */
import { spawn, spawnSync } from 'node:child_process';
import { createServer } from 'node:http';
import { existsSync, mkdirSync, mkdtempSync, readdirSync, readFileSync, rmSync, statSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

export const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..', '..');
export const ARTIFACTS = path.join(ROOT, 'tools', 'cdp', '.artifacts');
export const FRONTEND = path.join(ROOT, 'frontend');
export const FRONTEND_SRC = path.join(FRONTEND, 'src');
export const FRONTEND_SCRIPTS = path.join(FRONTEND, 'scripts');
export const DEMO_HTML = path.join(FRONTEND, 'design-demo', 'dora-design-demo.html');
export const API_BASE = process.env.DORA_API_BASE || 'http://127.0.0.1:8000/api';
export const BACKEND_HEALTH = `${API_BASE}/health`;

const CHROME_CANDIDATES = [
  process.env.DORA_CHROME,
  '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
  '/usr/bin/google-chrome',
  '/usr/bin/chromium',
  '/usr/bin/chromium-browser',
].filter(Boolean);
export const CHROME = CHROME_CANDIDATES.find((p) => existsSync(p));

export const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/** 页面脚本运行前安装的 toast 观察器：把每次出现的 `.toast` 文案按历史记录（P029）。 */
export const TOAST_OBSERVER = `(() => {
  window.__toastLog = window.__toastLog || [];
  const record = () => {
    const el = document.querySelector('.toast');
    const text = el ? (el.textContent || '').trim() : '';
    if (text && window.__toastLog[window.__toastLog.length - 1] !== text) window.__toastLog.push(text);
  };
  const start = () => { record(); new MutationObserver(record).observe(document.documentElement, { childList: true, subtree: true, characterData: true }); };
  if (document.documentElement) start(); else document.addEventListener('DOMContentLoaded', start);
})();`;

/** 开发态（Vite dev）没有单文件 demo 的引导脚本，需自己预置数据源，否则停在冷启动页。 */
export const SEED_DATASOURCE = `(() => {
  try {
    if (!localStorage.getItem('doraDataSource')) {
      localStorage.setItem('doraDataSource', JSON.stringify({ name: '门店经营数据.xlsx', kind: 'sample', at: '09:32', rows: 2847, fields: 36 }));
    }
  } catch (err) { console.info('[cdp] localStorage 不可写', err); }
})();`;

/** 启动 headless Chrome 并等 CDP 端口就绪；`close()` 会杀进程并删掉临时 profile。 */
export async function launchChrome({ port = 9300 + Math.floor(Math.random() * 400), headless = true } = {}) {
  if (!CHROME) {
    throw new Error('未找到 Chrome：可用 DORA_CHROME=/path/to/chrome 指定（macOS 默认 /Applications/Google Chrome.app/...）');
  }
  const profile = mkdtempSync(path.join(tmpdir(), 'dora-cdp-'));
  const args = [
    ...(headless ? ['--headless=new'] : []),
    `--remote-debugging-port=${port}`,
    `--user-data-dir=${profile}`,
    '--no-first-run',
    '--no-default-browser-check',
    '--disable-extensions',
    '--disable-gpu',
    '--hide-scrollbars',
    '--window-size=1440,960',
    'about:blank',
  ];
  const proc = spawn(CHROME, args, { stdio: ['ignore', 'ignore', 'pipe'] });
  const close = () => {
    try { proc.kill('SIGKILL'); } catch { /* 已退出 */ }
    try { rmSync(profile, { recursive: true, force: true }); } catch { /* 忽略 */ }
  };
  const deadline = Date.now() + 20000;
  while (Date.now() < deadline) {
    try {
      const res = await fetch(`http://127.0.0.1:${port}/json/version`);
      if (res.ok) return { port, proc, profile, close };
    } catch { /* 还没起来 */ }
    await sleep(150);
  }
  close();
  throw new Error(`Chrome 未在 20s 内就绪（CDP 端口 ${port}）`);
}

/** 建页 + 连 CDP。返回 `{ id, session }`；页面级 socket 直连（不走 flat session，P019）。 */
export async function newPage(port, url = 'about:blank') {
  const res = await fetch(`http://127.0.0.1:${port}/json/new?${encodeURIComponent(url)}`, { method: 'PUT' });
  if (!res.ok) throw new Error(`创建页面失败：HTTP ${res.status}（Chrome 111+ 起 /json/new 必须用 PUT）`);
  const target = await res.json();
  const session = await connect(target.webSocketDebuggerUrl);
  return { id: target.id, session };
}

export function connect(wsUrl) {
  return new Promise((resolve, reject) => {
    const ws = new WebSocket(wsUrl);
    let seq = 0;
    const pending = new Map();
    const listeners = new Set();
    ws.addEventListener('message', (ev) => {
      let msg;
      try { msg = JSON.parse(ev.data); } catch { return; }
      if (msg.id !== undefined && pending.has(msg.id)) {
        const { resolve: ok, reject: no } = pending.get(msg.id);
        pending.delete(msg.id);
        if (msg.error) no(new Error(`CDP 错误：${msg.error.message}`));
        else ok(msg.result);
        return;
      }
      for (const fn of listeners) fn(msg);
    });
    ws.addEventListener('open', () => resolve({
      send: (method, params = {}) => new Promise((ok, no) => {
        const id = ++seq;
        pending.set(id, { resolve: ok, reject: no });
        ws.send(JSON.stringify({ id, method, params }));
      }),
      on: (fn) => { listeners.add(fn); return () => listeners.delete(fn); },
      close: () => ws.close(),
    }));
    ws.addEventListener('error', () => reject(new Error(`无法连接 CDP WebSocket：${wsUrl}`)));
    ws.addEventListener('close', () => reject(new Error('CDP WebSocket 在建连阶段被关闭')));
  });
}

/** 开 Page/Runtime 域 + 注册「页面脚本前」的注入源（toast 观察器 / 数据源预置等）。 */
export async function preparePage(session, { initScripts = [] } = {}) {
  await session.send('Page.enable');
  await session.send('Runtime.enable');
  for (const source of initScripts) await session.send('Page.addScriptToEvaluateOnNewDocument', { source });
}

export async function goto(session, url, { waitSelector, timeout = 15000 } = {}) {
  await session.send('Page.navigate', { url });
  if (waitSelector) {
    await waitFor(session, `!!document.querySelector(${JSON.stringify(waitSelector)})`, {
      timeout,
      label: `页面出现 ${waitSelector}`,
    });
  }
}

export async function evaluate(session, expression, { awaitPromise = true } = {}) {
  const r = await session.send('Runtime.evaluate', { expression, awaitPromise, returnByValue: true, userGesture: true });
  if (r.exceptionDetails) {
    throw new Error(`页面表达式抛错：${r.exceptionDetails.exception?.description ?? r.exceptionDetails.text}`);
  }
  return r.result?.value;
}

export async function waitFor(session, expression, { timeout = 8000, interval = 100, label = expression } = {}) {
  const deadline = Date.now() + timeout;
  for (;;) {
    try {
      const v = await evaluate(session, expression);
      if (v) return v;
    } catch { /* 上下文切换中，重试 */ }
    if (Date.now() > deadline) throw new Error(`等待超时（${timeout}ms）：${label}`);
    await sleep(interval);
  }
}

/** 条件短暂不成立时不抛错，返回布尔（用于「应当可见」这类断言）。 */
export const visible = (session, expression, opts = {}) =>
  waitFor(session, expression, opts).then(() => true).catch(() => false);

export const bodyText = (session) => evaluate(session, 'document.body.innerText');
export const textOf = (session, selector) =>
  evaluate(session, `(document.querySelector(${JSON.stringify(selector)})?.textContent ?? '').trim()`);
export const countOf = (session, selector) =>
  evaluate(session, `document.querySelectorAll(${JSON.stringify(selector)}).length`);
export const hashOf = (session) => evaluate(session, 'location.hash');
export const toastLog = (session) => evaluate(session, 'window.__toastLog ?? []');
export const clickSelector = (session, selector) => evaluate(
  session,
  `(() => { const el = document.querySelector(${JSON.stringify(selector)}); if (!el) return false; el.click(); return true; })()`,
);
export const clickByText = (session, selector, text) => evaluate(
  session,
  `(() => { const el = [...document.querySelectorAll(${JSON.stringify(selector)})].find((e) => (e.textContent || '').includes(${JSON.stringify(text)})); if (!el) return false; el.click(); return true; })()`,
);

/** 静态文件服务器（单文件 demo 用；`/api/*` 自然 404 = 未连后端）。 */
export async function serveStatic(dir, { port = 0 } = {}) {
  const MIME = {
    '.html': 'text/html; charset=utf-8',
    '.js': 'text/javascript; charset=utf-8',
    '.css': 'text/css; charset=utf-8',
    '.json': 'application/json; charset=utf-8',
    '.svg': 'image/svg+xml',
    '.png': 'image/png',
  };
  const server = createServer((req, res) => {
    const rel = decodeURIComponent((req.url || '/').split('?')[0]);
    const file = path.join(dir, rel === '/' ? '/index.html' : rel);
    if (!file.startsWith(dir) || !existsSync(file) || !statSync(file).isFile()) {
      res.writeHead(404, { 'content-type': 'text/plain; charset=utf-8' });
      res.end('404');
      return;
    }
    res.writeHead(200, { 'content-type': MIME[path.extname(file)] ?? 'application/octet-stream', 'cache-control': 'no-store' });
    res.end(readFileSync(file));
  });
  await new Promise((ok) => server.listen(port, '127.0.0.1', ok));
  const actual = server.address().port;
  return {
    port: actual,
    url: `http://127.0.0.1:${actual}`,
    close: () => new Promise((ok) => { server.closeAllConnections?.(); server.close(ok); }),
  };
}

/** 递归取目录下最新 mtime（判断 demo 产物是否陈旧：P034）。 */
function newestMtime(dir) {
  let newest = 0;
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, entry.name);
    newest = Math.max(newest, entry.isDirectory() ? newestMtime(p) : statSync(p).mtimeMs);
  }
  return newest;
}

/**
 * 单文件 demo 就绪：**缺了或比 `frontend/src` / 生成器 `frontend/scripts` 旧**就重建
 * （`npm run demo:html`），保证用例自持。
 *
 * 为什么要查陈旧（P034）：产物不入库、`npm run demo:html` 是手动步骤；拿旧产物做行为/视觉取证会得出
 * 「改动没生效」或「问题不存在」的错误结论（2026-09-26 实测产物比源码旧 10 天）。
 * 为什么还要比 `frontend/scripts`（P038）：只改**生成器**（如 `PANEL_CSS` 覆盖样式）时 `frontend/src`
 * 一行未动，产物照样是旧的 → 用例会拿旧布局「验」新改动。
 * 逃生口：`DORA_SKIP_DEMO_REBUILD=1` 跳过重建（仅在确认产物新鲜时使用）。
 */
export async function ensureDemoHtml() {
  const exists = existsSync(DEMO_HTML);
  const stale = exists && Math.max(newestMtime(FRONTEND_SRC), newestMtime(FRONTEND_SCRIPTS)) > statSync(DEMO_HTML).mtimeMs;
  if (exists && (!stale || process.env.DORA_SKIP_DEMO_REBUILD === '1')) return DEMO_HTML;
  console.log(exists ? '· 单文件 demo 比 frontend/src（或生成器 scripts）旧 → 重建（npm run demo:html）' : '· 未发现单文件 demo → 现场构建（cd frontend && npm run demo:html）');
  const r = spawnSync('npm', ['run', 'demo:html'], { cwd: FRONTEND, stdio: 'inherit', env: process.env });
  if (r.status !== 0 || !existsSync(DEMO_HTML)) throw new Error('单文件 demo 构建失败（见上方输出）');
  return DEMO_HTML;
}

/** 起 Vite dev server（在线用例要靠它的 `/api` 代理打到 :8000）。 */
export async function startViteDev({ port = 5173, env = {} } = {}) {
  const vite = path.join(FRONTEND, 'node_modules', '.bin', 'vite');
  if (!existsSync(vite)) throw new Error('未安装前端依赖：cd frontend && npm install');
  // P028：后台启动 Vite 必须重定向 stdin，否则会被 SIGTTIN 挂起（端口在听、却零响应）
  const proc = spawn(vite, ['--port', String(port), '--strictPort', '--host', '127.0.0.1'], {
    cwd: FRONTEND,
    stdio: ['ignore', 'pipe', 'pipe'],
    env: { ...process.env, VITE_PROXY_TARGET: API_BASE.replace(/\/api$/, ''), ...env },
  });
  const deadline = Date.now() + 40000;
  while (Date.now() < deadline) {
    try {
      const res = await fetch(`http://127.0.0.1:${port}/`);
      if (res.ok) return { port, url: `http://127.0.0.1:${port}`, close: () => { try { proc.kill('SIGKILL'); } catch { /* 已退出 */ } } };
    } catch { /* 还在启动 */ }
    await sleep(250);
  }
  try { proc.kill('SIGKILL'); } catch { /* 已退出 */ }
  throw new Error(`Vite dev server 未在 40s 内就绪（端口 ${port}）`);
}

/** 后端在线判定（在线用例前置；不在线就 SKIP 并说明原因，不假红也不假绿）。 */
export async function backendUp(timeoutMs = 2000) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const res = await fetch(BACKEND_HEALTH, { signal: ctrl.signal });
    return res.ok;
  } catch {
    return false;
  } finally {
    clearTimeout(timer);
  }
}

/** 直连后端取 JSON（在线用例的「契约级」断言用，走 node fetch 不过 Vite 代理）。 */
export const apiJson = (path) => fetch(`${API_BASE}${path}`).then(async (r) => {
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
});

export async function screenshot(session, name) {
  mkdirSync(ARTIFACTS, { recursive: true });
  const r = await session.send('Page.captureScreenshot', { format: 'png' });
  const file = path.join(ARTIFACTS, `${name}.png`);
  writeFileSync(file, Buffer.from(r.data, 'base64'));
  console.log(`· 截图（证据）：${path.relative(ROOT, file)}`);
  return file;
}

/** 断言收集器：逐条打印 PASS/FAIL，末尾给 通过数/总数 + 退出码。 */
export function createSuite(title) {
  const results = [];
  console.log(`\n=== ${title} ===`);
  const suite = {
    check(name, ok, detail = '') {
      const pass = !!ok;
      results.push({ name, pass });
      console.log(`${pass ? '[PASS]' : '[FAIL]'} ${name}${detail ? ` — ${detail}` : ''}`);
      return pass;
    },
    failed: () => results.filter((r) => !r.pass).length,
    summary() {
      const pass = results.length - suite.failed();
      console.log(`${title}：${pass}/${results.length} ${suite.failed() ? 'FAIL' : 'ALL PASS'}`);
      return suite.failed();
    },
  };
  return suite;
}

/** 用例统一收尾：逆序清理资源 → 打印结论 → 设置退出码。 */
export async function finish(suite, closers = []) {
  for (const close of [...closers].reverse()) {
    try { await close(); } catch { /* 忽略清理失败 */ }
  }
  const failed = suite.summary();
  process.exitCode = failed || process.exitCode ? 1 : 0;
  return failed;
}

/** 用例中断（例如 Chrome 起不来）：显式 FAIL，不让异常变成「静默绿」。 */
export function fatal(err) {
  console.error(`\n[FAIL] 用例中断：${err instanceof Error ? err.stack ?? err.message : err}`);
  process.exitCode = 1;
}


/** 模拟“未获得 HTTP 响应”，可撤销；HTTP 4xx/5xx 另用正常响应测试。 */
export async function failRequests(session, urlPattern, { method } = {}) {
  const handler = ({ requestId, request }) => {
    void session.send(!method || request.method === method ? 'Fetch.failRequest' : 'Fetch.continueRequest',
      !method || request.method === method ? { requestId, errorReason: 'ConnectionFailed' } : { requestId });
  };
  const off = session.on(message => { if (message.method === 'Fetch.requestPaused') handler(message.params); });
  await session.send('Fetch.enable', { patterns: [{ urlPattern }] });
  return async () => { await session.send('Fetch.disable'); off(); };
}
