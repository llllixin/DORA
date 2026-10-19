#!/usr/bin/env node
import {
  API_BASE, SEED_DATASOURCE, TOAST_OBSERVER, backendUp, clickByText, createSuite, evaluate,
  fatal, finish, goto, launchChrome, newPage, preparePage, screenshot, startViteDev, toastLog, visible,
} from './lib/cdp.mjs';
const suite=createSuite('fullstack_ui_check（上传、图表、空态、离线写入）');
let vite,chrome,session,watchId;
async function request(path, method='GET', payload) {
  const res=await fetch(`${API_BASE}${path}`,{method,headers:{'Content-Type':'application/json'},body:payload?JSON.stringify(payload):undefined});
  if(!res.ok)throw new Error(`HTTP ${res.status} ${await res.text()}`);
  return res.json();
}
try {
  if(!(await backendUp()))throw new Error('需要隔离 API 在线');
  const form=new FormData();
  form.append('file',new Blob(['metric_key,label,value\nmargin,2026-09-04,14\nmargin,2026-09-03,15\nmargin,2026-09-02,16\nmargin,2026-09-01,17\n']),'margin.csv');
  const uploaded=await fetch(`${API_BASE}/datasets`,{method:'POST',body:form});
  suite.check('倒序且缺省维度的真实上传成功',uploaded.ok);
  vite=await startViteDev({port:5188,env:{VITE_API_MODE:'auto'}});
  chrome=await launchChrome();({session}=await newPage(chrome.port));
  const errors=[];session.on(m=>{if(m.method==='Runtime.exceptionThrown')errors.push(m.params.exceptionDetails.text);});
  await preparePage(session,{initScripts:[SEED_DATASOURCE,TOAST_OBSERVER]});
  await goto(session,`${vite.url}/#page=insight&type=problem&idx=0`,{waitSelector:'[data-chart-source=engine]'});
  suite.check('真实图表显示上传后的 14 而非样例 18.1',await evaluate(session,`!!document.querySelector('[data-chart-source=engine] [data-value="14"]') && !document.querySelector('[data-chart-source=engine] [data-value="18.1"]')`));
  suite.check('图表按日期排序',await evaluate(session,`[...document.querySelectorAll('[data-chart-source=engine] [data-value]')].map(x=>Number(x.dataset.value)).join(',')==='17,16,15,14'`));
  // auto 模式 HTTP 错误不能触发“创建成功”fallback。
  suite.check('auto 模式真实 404 拒绝建档',await evaluate(session,`(async()=>{const a=await import('/src/services/doraApi.ts');try{await a.createAction('missing-insight',true);return false}catch{return true}})()`));
  // 明确的 503 也是服务端响应，不能作为未获响应的 offline。
  const rejectServer=session.on(m=>{if(m.method==='Fetch.requestPaused')void session.send('Fetch.fulfillRequest',{requestId:m.params.requestId,responseCode:503,responseHeaders:[{name:'Content-Type',value:'application/json'}],body:Buffer.from(JSON.stringify({detail:'数据源不可用'})).toString('base64')});});
  await session.send('Fetch.enable',{patterns:[{urlPattern:'*/api/action/cases'}]});
  suite.check('auto 模式明确 503 上抛并保留原因',await evaluate(session,`(async()=>{const a=await import('/src/services/doraApi.ts');try{await a.createAction('p1',true);return false}catch(e){return e.message.includes('数据源不可用')}})()`));
  await session.send('Fetch.disable');rejectServer();
  await screenshot(session,'fullstack-live-chart');
  const watch=await request('/watch','POST',{text:'帮我关注华东销售额，如果连续三天下降就提醒我'});
  watchId=watch.target.id;
  await goto(session,`${vite.url}/#page=watch`,{waitSelector:'.delegate-state'});
  await visible(session,`[...document.querySelectorAll('.rowbtn')].some(x=>x.textContent.includes('删除'))`,{label:'委托行删除按钮出现'});
  // 拦截写操作为网络失败，GET 仍返回真实行，验证状态不被前端伪改。
  const stop=session.on(m=>{
    if(m.method!=='Fetch.requestPaused')return;
    const {requestId,request}=m.params;
    void session.send(request.method==='GET'?'Fetch.continueRequest':'Fetch.failRequest',request.method==='GET'?{requestId}:{requestId,errorReason:'ConnectionFailed'});
  });
  await session.send('Fetch.enable',{patterns:[{urlPattern:'*/api/watch*'}]});
  const rejected=await evaluate(session,`(async()=>{const a=await import('/src/services/doraApi.ts');const id=${JSON.stringify(watchId)};const calls=[()=>a.setWatchStatusStrict(id,'paused'),()=>a.deleteWatch(id),()=>a.checkWatchStrict(id),()=>a.createWatch('帮我关注华东销售额，如果连续三天下降就提醒我')];const results=[];for(const call of calls){try{await call();results.push(false)}catch{results.push(true)}}return results})()`);
  suite.check('断网暂停/删除/检查/创建全部拒绝伪成功',rejected.length===4&&rejected.every(Boolean),JSON.stringify(rejected));
  const deleteClicked=await clickByText(session,'.rowbtn','删除');
  suite.check('页面删除失败提示可见',deleteClicked&&await visible(session,`document.body.innerText.includes('删除未完成')`));
  suite.check('服务端委托仍然存在',(await request('/watch')).some(x=>x.id===watchId));
  await session.send('Fetch.disable');stop();
  // API 成功但列表为空是正常业务状态。
  const empty=session.on(m=>{
    if(m.method==='Fetch.requestPaused')void session.send('Fetch.fulfillRequest',{requestId:m.params.requestId,responseCode:200,responseHeaders:[{name:'Content-Type',value:'application/json'}],body:Buffer.from('[]').toString('base64')});
  });
  await session.send('Fetch.enable',{patterns:[{urlPattern:'*/api/insights*'}]});
  // 仅改 hash 不会重新挂载 App；加查询参数强制新文档，让初始化同步真正读取空列表。
  await goto(session,`${vite.url}/?empty=1#page=insight&type=problem&idx=0`,{waitSelector:'.main'});
  suite.check('空洞察显示空态且不崩溃',await visible(session,`document.body.innerText.includes('当前没有此类洞察')`));
  suite.check('无未捕获页面异常',errors.length===0,errors.join(';'));
  await screenshot(session,'fullstack-empty-state');
  await session.send('Fetch.disable');empty();
}catch(err){fatal(err);}
finally{
  if(watchId)await request(`/watch/${watchId}`,'DELETE').catch(()=>{});
  await request('/datasets/sample','POST',{}).catch(()=>{});
}
await finish(suite,[()=>session?.close(),()=>vite?.close(),()=>chrome?.close()]);
