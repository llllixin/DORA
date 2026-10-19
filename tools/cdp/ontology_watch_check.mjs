/** A01: real current UI + disposable API. Never uses the user's normal database. */
import { spawn } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { ROOT, SEED_DATASOURCE, launchChrome, newPage, preparePage, goto, evaluate, waitFor, clickByText, startViteDev, screenshot, sleep } from './lib/cdp.mjs';

if (process.env.DATABASE_URL !== 'postgresql+psycopg://dora_a01:dora_a01@127.0.0.1:55449/dora_a01') throw new Error('A01 disposable DB required');
const dir = path.join(ROOT, 'output/a01-verification');
fs.mkdirSync(dir, { recursive: true });
const log = fs.openSync(path.join(dir, 'browser-api.log'), 'w');
const environment = { ...process.env, DORA_REASONING_PROVIDER: 'template', DORA_LLM_API_KEY: '', DORA_RAG_ANSWER_PROVIDER: 'template', DORA_RAG_EMBEDDING_PROVIDER: 'hash', DORA_RAG_OPENAI_API_KEY: '', OPENAI_API_KEY: '' };
const api = spawn('/Users/tomara/miniforge3/bin/python3', ['-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '8049'], { cwd: path.join(ROOT, 'backend'), env: environment, stdio: ['ignore', log, log] });
let vite, chrome, session;
const checks = [];
function check(name, value) { checks.push({ name, passed: !!value }); if (!value) throw new Error(name); console.log('PASS:', name); }
try {
  let ready = false;
  for (let i = 0; i < 100; i++) {
    if (api.exitCode !== null) throw new Error('test API exited');
    try { if ((await fetch('http://127.0.0.1:8049/api/health')).ok) { ready = true; break; } } catch {}
    await sleep(100);
  }
  if (!ready) throw new Error('test API not ready');
  vite = await startViteDev({ port: 5179, env: { VITE_API_MODE: 'http', VITE_PROXY_TARGET: 'http://127.0.0.1:8049' } });
  chrome = await launchChrome();
  ({ session } = await newPage(chrome.port));
  await preparePage(session, { initScripts: [SEED_DATASOURCE] });
  await goto(session, `${vite.url}/#page=watch`, { waitSelector: '#watchInput' });
  check('default example uses actual east order concept', (await evaluate(session, "document.querySelector('#watchInput').value")).includes('华东订单量'));
  check('suggestions no longer offer wrong sales/order aliases', await evaluate(session, "[...document.querySelectorAll('.suggest')].some(b=>b.textContent==='关注华东订单量') && ![...document.querySelectorAll('.suggest')].some(b=>['关注华东销售','关注新品增长','关注大额订单'].includes(b.textContent))"));
  await clickByText(session, 'button', '让 Dora 理解');
  await waitFor(session, "!!document.querySelector('.delegate-result.show')");
  check('real parse displays east order + east dimension', await evaluate(session, "document.querySelector('.intent-grid').textContent.includes('华东订单量') && document.querySelector('.intent-grid').textContent.includes('华东')"));
  check('old sales phrase explicitly rejected by live endpoint', await evaluate(session, "(async()=>{const a=await import('/src/services/doraApi.ts');const r=await a.parseWatch('帮我关注华东销售额，如果连续三天下降就提醒我');return r.ok===false&&!!r.unsupported?.length})()"));
  check('live metric hint carries correct physical key and scope', await evaluate(session, "(async()=>{const r=await fetch('/api/rag/answer',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({question:'最新华东订单量是多少'})}).then(r=>r.json());return r.status==='tool_required'&&r.tool_args.metric_key==='east_orders'&&r.tool_args.dimension==='华东'})()"));
  check('live financial ambiguity yields clarification', await evaluate(session, "(async()=>{const r=await fetch('/api/rag/answer',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({question:'今天毛利率是多少'})}).then(r=>r.json());return r.status==='clarification_required'&&r.citations.length===0})()"));
  await screenshot(session, 'ontology-a01-watch');
  console.log('A01 browser checks passed');
} finally {
  session?.close(); chrome?.close(); await vite?.close();
  api.kill('SIGTERM'); fs.closeSync(log);
  fs.writeFileSync(path.join(dir, 'browser-results.json'), JSON.stringify({ checks, disposableDatabase: 'dora_a01' }, null, 2));
}
