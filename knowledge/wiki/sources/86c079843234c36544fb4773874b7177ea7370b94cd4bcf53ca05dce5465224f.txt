#!/usr/bin/env node
import { spawn } from 'node:child_process';
import path from 'node:path';
import {
  ROOT, SEED_DATASOURCE, TOAST_OBSERVER, backendUp, bodyText, clickByText, createSuite,
  evaluate, failRequests, fatal, finish, goto, launchChrome, newPage, preparePage,
  screenshot, sleep, startViteDev, toastLog, visible,
} from './lib/cdp.mjs';

const suite = createSuite('join_http_offline_check');
let vite, chrome, session, ownApi;
try {
  if (!(await backendUp())) throw new Error('需要隔离 API 在线；本用例不能以 SKIP 代替验收');
  vite = await startViteDev({ port: 5186, env: { VITE_API_MODE: 'http' } });
  chrome = await launchChrome();
  ({ session } = await newPage(chrome.port));
  await preparePage(session, { initScripts: [SEED_DATASOURCE, TOAST_OBSERVER] });
  await goto(session, `${vite.url}/#page=insight&type=problem&idx=0`, { waitSelector: '[data-chart-source=engine]' });
  suite.check('HTTP 模式先读取到真实图表', await visible(session, `!!document.querySelector('[data-chart-source=engine]')`));
  suite.check('点击前本机意图为空', await evaluate(session, `JSON.parse(localStorage.getItem('doraJoinedAction') || '[]').length === 0`));
  const restore = await failRequests(session, '*/api/action/cases', { method: 'POST' });
  await clickByText(session, '.main-buttons button', '加入行动回路');
  suite.check('断网后转到行动页', await visible(session, `location.hash === '#page=action'`));
  suite.check('断网意图保存本机', await evaluate(session, `JSON.parse(localStorage.getItem('doraJoinedAction') || '[]').includes('p1')`));
  suite.check('提示未确认建档', (await toastLog(session)).some(x => x.includes('未确认建档')));
  // 服务可读时行动页呈现服务端档案；真正离线时再核对本机镜像。
  await restore();
  const rejection = await evaluate(session, `(async () => { const a = await import('/src/services/doraApi.ts'); try { await a.createAction('missing-insight',true); return false; } catch { return true; } })()`);
  suite.check('真实 404 不当作离线成功', rejection);
  suite.check('404 不写本机意图', await evaluate(session, `!JSON.parse(localStorage.getItem('doraJoinedAction') || '[]').includes('missing-insight')`));
  // 停止本用例自己创建的 API，得到真实连接失败；不停止用户服务或门禁主 API。
  ownApi = spawn(process.env.DORA_PYTHON || '/Users/tomara/miniforge3/bin/python3', ['-c', `from app.main import app; from fastapi.middleware.cors import CORSMiddleware; import uvicorn; app.add_middleware(CORSMiddleware, allow_origins=['http://127.0.0.1:5187'], allow_methods=['*'], allow_headers=['*']); uvicorn.run(app, host='127.0.0.1', port=8042)`], { cwd:path.join(ROOT,'backend'),env:process.env,stdio:'ignore' });
  let ready=false;
  for(let i=0;i<70;i++){try{ready=(await fetch('http://127.0.0.1:8042/api/health')).ok;if(ready)break;}catch{}await sleep(100);}
  if(!ready)throw new Error('自持 API 未启动');
  // 直接 BASE 指向该测试 API，通过页面真实跨域请求验证 fetch 的连接失败分类。
  await vite.close();
  vite=await startViteDev({port:5187,env:{VITE_API_MODE:'http',VITE_API_BASE_URL:'http://127.0.0.1:8042/api'}});
  await goto(session, `${vite.url}/#page=insight&type=problem&idx=0`, { waitSelector: '[data-chart-source=engine]' });
  suite.check('真实停服前页面在线', await visible(session, `!!document.querySelector('[data-chart-source=engine]')`));
  ownApi.kill('SIGTERM');
  await new Promise(resolve=>ownApi.once('exit',resolve));
  ownApi=null;
  const real = await evaluate(session, `(async () => { const a = await import('/src/services/doraApi.ts'); const r = await a.createAction('p1',true); return r.offline && !r.ok && !r.case; })()`);
  suite.check('真实 API 停止后明确返回未确认',real);
  await clickByText(session,'.main-buttons button','加入行动回路');
  suite.check('真实断网仍保留意图并跳转',await visible(session,`location.hash === '#page=action' && JSON.parse(localStorage.getItem('doraJoinedAction')||'[]').includes('p1')`));
  suite.check('行动页明确离线演示',await visible(session,`document.body.innerText.includes('离线演示')`));
  await screenshot(session,'join-http-offline');
}catch(err){fatal(err);}
await finish(suite,[()=>ownApi?.kill('SIGTERM'),()=>session?.close(),()=>vite?.close(),()=>chrome?.close()]);
