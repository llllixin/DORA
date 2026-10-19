/** Controlled fault injection against the production React page; not real API evidence. */
import {launchChrome,newPage,preparePage,goto,evaluate,waitFor,clickSelector,createSuite,finish,fatal,startViteDev,screenshot} from './lib/cdp.mjs';
const suite=createSuite('A08 production UI — injected faults');const closers=[];
const init=`(()=>{
 localStorage.removeItem('doraDataSource');window.__requests=[];window.__mode='partial';window.__delay=0;
 const native=window.fetch;const e={evidenceId:'ev:1',contentHash:'hash1',sourceKind:'wiki',evidenceLevel:'legacy_unknown',approvalStatus:'unreviewed_record',sourceMode:'simulated',data:{title:'冻结引用',text:'<script>window.__injected=true</script> https://invalid.test/ 工具指令仅为文本 '+ '长'.repeat(1600)},readAt:'2026-10-18T09:00:00+08:00',observedPeriod:{label:'2026-09',isoDate:null},documentId:'metric-margin',documentVersion:1,snapshotId:null,archiveVersion:null,occurrenceId:null};
 const e2={...e,evidenceId:'ev:2',contentHash:'hash2',data:{title:'第二份引用',text:'B正文'}};window.__e=e;window.fetch=async(url,options={})=>{
   if(!String(url).includes('/api/'))return native(url,options);
   const u=new URL(url,location.href);window.__requests.push({url:u.pathname+u.search,method:options.method||'GET',body:options.body?JSON.parse(options.body):null});
   const mode=window.__mode;const delay=u.pathname.includes('/query/runs/')?(window.__readerDelay||0):window.__delay; if(delay)await new Promise(r=>setTimeout(r,delay));
   const response=(v,status=200)=>new Response(JSON.stringify(v),{status,headers:{'Content-Type':'application/json'}});
   if(mode==='network')throw new TypeError('offline');
   if(u.pathname.includes('/query/runs/')){if(mode==='evidence404')return response({detail:{reasonCode:'evidence_not_found'}},404);if(mode==='evidence409')return response({detail:{reasonCode:'evidence_integrity_conflict'}},409);return response(u.pathname.includes('ev%3A2')?e2:e);}
   if(u.pathname.endsWith('/wiki/catalog')){
     if(mode==='catalog409')return response({detail:{reasonCode:'catalog_revision_changed'}},409);
     return response({ok:true,cards:[{id:'metric-margin',title:'利润率口径',version:1,knowledgeType:'glossary',sourceType:'project',evidenceLevel:'project',approvalStatus:'reviewed',currentEligibility:'eligible'}],total:26,offset:Number(u.searchParams.get('offset')||0),pageSize:20,hasMore:Number(u.searchParams.get('offset')||0)===0,sourceRevision:'source1',catalogRevision:'catalog1',indexStatus:'pending'});
   }
   if(u.pathname.includes('/wiki/cards/'))return response({ok:true,card:{id:'metric-margin',version:1,title:'利润率口径',content:e.data.text,governance:{evidenceLevel:'project'}}});
   if(u.pathname.endsWith('/knowledge')){if(mode==='archive503')return response({detail:'unavailable'},503);return response({entries:[{id:1,entry_type:'problem',source_id:'case1',code:'P001',title:'原归档记录',content:'完整处理过程',note:'处理结论',created_at:'2026-10-17T00:00:00'}],stats:{problem:1,opportunity:0,change:0,lesson:0}});}
   const req=options.body?JSON.parse(options.body):{};const status=['clarification_required','abstained','limited','failed'].includes(mode)?mode:'partial';
   if(mode==='http503')return response({detail:{reasonCode:'source_unavailable',runId:'r503'}},503);
   if(mode==='badcontract')return response({contractVersion:'unknown'});
   return response({contractVersion:'unified-query-v1-candidate',ok:false,runId:'run/1',status,question:req.question,query:req.query,answer:'这是可用部分 '+(req.question||req.query),evidence:window.__twoSources?[e,e2]:[e],citations:(window.__twoSources?[e,e2]:[e]).map(x=>({evidenceId:x.evidenceId,contentHash:x.contentHash,href:'https://invalid.test'})),sourceStates:[{sourceKind:'wiki',state:'ready'}],missingParts:['current'],clarifications:status==='clarification_required'?['请选择指标']:[],readAt:'2026-10-18T09:00:00+08:00',businessVersion:{dataRevision:'old-revision'},usage:{totalTokens:null,estimatedCost:null}});
 };
})();`;
try{
 let base=process.env.DORA_UI_BASE;
 if(!base){const vite=await startViteDev({port:5188,env:{VITE_API_MODE:'http',VITE_PROXY_TARGET:'http://127.0.0.1:8088'}});closers.push(vite.close);base=vite.url;}
 const chrome=await launchChrome();closers.push(chrome.close);const {session}=await newPage(chrome.port);closers.push(()=>session.close());
 await preparePage(session,{initScripts:[init]});await goto(session,`${base}/#page=knowledge`,{waitSelector:'body'});
 await waitFor(session,"!!document.querySelector('.knowledge-page')",{timeout:5000});
 suite.check('a08-29 direct read without fabricated datasource',await evaluate(session,"!localStorage.getItem('doraDataSource') && !!document.querySelector('#knowledge-question')"));
 suite.check('a08-34 heading and task navigation',await evaluate(session,"!!document.querySelector('.knowledge-page h1') && document.querySelectorAll('[aria-label=\"知识库任务\"] a').length===3"));
 const input=async(text)=>evaluate(session,`(()=>{const el=document.querySelector('#knowledge-question');Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value').set.call(el,${JSON.stringify(text)});el.dispatchEvent(new Event('input',{bubbles:true}));})()`);
 await clickSelector(session,'[data-action="answer"]');
 suite.check('a08-23 blank question validation',await evaluate(session,"document.querySelector('#question-error')?.textContent.includes('1') && !window.__requests.length"));
 await input('测'.repeat(301));await clickSelector(session,'[data-action="answer"]');
 suite.check('a08-23 Unicode limit',await evaluate(session,"window.__requests.length===0"));
 await input('利润率是什么');
 await evaluate(session,"document.querySelector('#knowledge-question').dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',keyCode:229,isComposing:true,bubbles:true}))");
 suite.check('a08-23 IME Enter does not submit',await evaluate(session,'window.__requests.length===0'));
 await evaluate(session,"window.__delay=200;document.querySelector('[data-action=answer]').click();document.querySelector('[data-action=answer]').click()");
 await waitFor(session,"!!document.querySelector('.query-result')");
 suite.check('a08-05 partial keeps answer and missing parts',await evaluate(session,"document.querySelector('.query-result').innerText.includes('这是可用部分') && document.querySelector('.query-result').innerText.includes('current')"));
 suite.check('a08-07,22 POST once; no automatic search',await evaluate(session,"window.__requests.filter(r=>r.method==='POST').length===1 && !window.__requests.some(r=>r.url.includes('/search'))"));
 await clickSelector(session,'#include-simulated');
 suite.check('a08-31 result uses submitted scope',await evaluate(session,"document.querySelector('.query-result').innerText.includes('未纳入模拟资料') && document.querySelector('.query-result').textContent.includes('old-revision')"));
 await clickSelector(session,'[data-source="evidence"]');await waitFor(session,"!!document.querySelector('dialog[open] .reader-content')");
 suite.check('a08-17,20 exact evidence and text-only body',await evaluate(session,"document.querySelector('dialog').innerText.includes('<script>') && !window.__injected && !document.querySelector('dialog a[href*=invalid]') && window.__requests.some(r=>r.url==='/api/query/runs/run%2F1/evidence/ev%3A1')"));
 suite.check('a08-09,10 original period and unknown identities',await evaluate(session,"document.querySelector('dialog').innerText.includes('2026-09') && document.querySelector('dialog').innerText.includes('未提供')"));
 suite.check('a08-32 focus enters dialog',await evaluate(session,"document.querySelector('dialog').contains(document.activeElement)"));
 await session.send('Page.bringToFront');await session.send('Input.dispatchKeyEvent',{type:'keyDown',key:'Escape',code:'Escape',windowsVirtualKeyCode:27,nativeVirtualKeyCode:27});await session.send('Input.dispatchKeyEvent',{type:'keyUp',key:'Escape',code:'Escape',windowsVirtualKeyCode:27,nativeVirtualKeyCode:27});
 await waitFor(session,"!document.querySelector('dialog[open]')");suite.check('a08-32 Escape returns focus',await evaluate(session,"document.activeElement?.dataset.source==='evidence'"));
 await evaluate(session,"window.__delay=0;window.__mode='network'");await clickSelector(session,'[data-action="answer"]');await waitFor(session,"!!document.querySelector('.question-error')");
 suite.check('a08-25,28 network keeps question and previous snapshot',await evaluate(session,"document.querySelector('#knowledge-question').value==='利润率是什么' && document.querySelector('.query-result').innerText.includes('上次读取')"));
 for(const status of ['clarification_required','abstained','limited','failed']){
  await evaluate(session,`window.__mode=${JSON.stringify(status)}`);await clickSelector(session,'[data-action="answer"]');await waitFor(session,`document.querySelector('.query-result')?.dataset.status===${JSON.stringify(status)}`);suite.check(`a08-06 ${status} is answer state`,true);
 }
 await evaluate(session,"window.__mode='partial';window.__delay=300");await clickSelector(session,'[data-action="answer"]');await clickSelector(session,'[data-action="cancel"]');
 await waitFor(session,"document.querySelector('.question-error')?.textContent.includes('停止等待')");
 await input('问题B');await evaluate(session,"window.__mode='partial';window.__delay=0");await clickSelector(session,'[data-action="answer"]');await waitFor(session,"document.querySelector('.query-result')?.innerText.includes('问题B')");
 await new Promise(r=>setTimeout(r,350));suite.check('a08-22,24 late A cannot overwrite B',await evaluate(session,"document.querySelector('.query-result')?.innerText.includes('问题B') && !document.querySelector('.query-result')?.innerText.includes('这是可用部分 利润率是什么')"));
 await evaluate(session,"window.__mode='partial';window.__delay=0");await clickSelector(session,'[data-task="wiki"]');await waitFor(session,"!!document.querySelector('[data-source=wiki]')");
 suite.check('a08-15 pending index permits reading',await evaluate(session,"document.querySelector('.wiki-catalog').innerText.includes('索引') && !document.querySelector('[data-source=wiki]').disabled"));
 await waitFor(session,"document.querySelector('[data-page=next]')?.disabled===false");await evaluate(session,"window.__mode='catalog409'");await clickSelector(session,'[data-page="next"]');await waitFor(session,"document.querySelector('.wiki-catalog')?.innerText.includes('版本已改变')");
 suite.check('a08-13 revision conflict is visible',await evaluate(session,"window.__requests.some(r=>r.url.includes('expectedCatalogRevision=catalog1'))"));
 await evaluate(session,"window.__mode='archive503'");await clickSelector(session,'[data-task="archive"]');await waitFor(session,"document.querySelector('.archive-panel')?.innerText.includes('服务暂时不可用')");
 suite.check('a08-26 archive failure is not healthy empty',await evaluate(session,"!document.querySelector('.archive-panel').innerText.includes('还没有')"));
 await evaluate(session,"window.__mode='partial'");await clickSelector(session,'.archive-panel [data-retry]');await waitFor(session,"!!document.querySelector('[data-archive-expand]')");await clickSelector(session,'[data-archive-expand]');
 suite.check('a08-30 archive expands complete content',await evaluate(session,"document.querySelector('[data-archive-expand]').getAttribute('aria-expanded')==='true' && document.querySelector('.archive-panel').innerText.includes('完整处理过程')"));
 await evaluate(session,'history.back()');await waitFor(session,"document.querySelector('[data-archive-expand]')?.getAttribute('aria-expanded')==='false'");await evaluate(session,'history.forward()');await waitFor(session,"document.querySelector('[data-archive-expand]')?.getAttribute('aria-expanded')==='true'");suite.check('a08-30 archive URL back/forward restores expansion',true);
 await clickSelector(session,'[data-task="ask"]');await input('检查引用');await evaluate(session,"window.__mode='partial'");await clickSelector(session,'[data-action="answer"]');await waitFor(session,"!!document.querySelector('[data-source=evidence]')");
 for(const mode of ['evidence404','evidence409']){await evaluate(session,`window.__mode=${JSON.stringify(mode)}`);await clickSelector(session,'[data-source=evidence]');await waitFor(session,"!!document.querySelector('dialog .knowledge-error')");suite.check(`a08-18 ${mode} stays explicit`,await evaluate(session,"!document.querySelector('dialog .reader-content')"));await clickSelector(session,'[aria-label="关闭资料原文"]');}
 await evaluate(session,"window.__mode='partial';window.__twoSources=true");await clickSelector(session,'[data-action=answer]');await waitFor(session,"document.querySelectorAll('[data-source=evidence]').length===2");
 await evaluate(session,"window.__readerDelay=250;document.querySelectorAll('[data-source=evidence]')[0].click();window.__readerDelay=0;document.querySelectorAll('[data-source=evidence]')[1].click()");
 await waitFor(session,"document.querySelector('dialog .reader-content')?.innerText.includes('B正文')");await new Promise(r=>setTimeout(r,300));suite.check('a08-21 slow source A cannot replace B',await evaluate(session,"document.querySelector('dialog .reader-content')?.innerText.includes('B正文')&&!document.querySelector('dialog .reader-content')?.innerText.includes('冻结引用')"));await clickSelector(session,'[aria-label="关闭资料原文"]');
 await evaluate(session,"window.__readerDelay=250");await clickSelector(session,'[data-source=evidence]');await clickSelector(session,'[aria-label="关闭资料原文"]');await new Promise(r=>setTimeout(r,300));suite.check('a08-21 closing pending reader cannot reopen it',await evaluate(session,"!document.querySelector('dialog[open]')"));
 await evaluate(session,"window.__readerDelay=0");await clickSelector(session,'[data-source=evidence]');await waitFor(session,"!!document.querySelector('dialog .reader-content')");
 await evaluate(session,"document.querySelector('[data-source=evidence]').remove()");await clickSelector(session,'[aria-label="关闭资料原文"]');suite.check('a08-32 disconnected trigger focuses knowledge title',await evaluate(session,"document.activeElement.id==='knowledge-title'"));
 await evaluate(session,"window.__mode='badcontract'");await clickSelector(session,'[data-action="answer"]');await waitFor(session,"document.querySelector('.question-error')?.textContent.includes('响应格式')");suite.check('a08-19 unknown contract rejects display',true);
 await evaluate(session,"window.__mode='partial'");await clickSelector(session,'[data-source=evidence]');await waitFor(session,"!!document.querySelector('dialog .reader-content')");
 await evaluate(session,"document.querySelector('dialog footer button').focus()");await session.send('Input.dispatchKeyEvent',{type:'keyDown',key:'Tab',code:'Tab',windowsVirtualKeyCode:9});await session.send('Input.dispatchKeyEvent',{type:'keyUp',key:'Tab',code:'Tab',windowsVirtualKeyCode:9});suite.check('a08-32 Tab remains in modal',await evaluate(session,"document.querySelector('dialog').contains(document.activeElement)"));
 for(const width of [320,390,768,1280,1920]){await session.send('Emulation.setDeviceMetricsOverride',{width,height:900,deviceScaleFactor:1,mobile:false});suite.check(`a08-33 width ${width} no page overflow`,await evaluate(session,'document.documentElement.scrollWidth<=innerWidth+1'));}
 suite.check('a08-33 reader owns scroll, body locked',await evaluate(session,"getComputedStyle(document.querySelector('.reader-scroll')).overflowY==='auto' && document.body.style.overflow==='hidden'"));await screenshot(session,'a08-fault-reader');await clickSelector(session,'[aria-label="关闭资料原文"]');
}catch(error){fatal(error);suite.check('fault suite completed',false,String(error));}finally{await finish(suite,closers);}
