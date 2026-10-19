// Exercises the real parsers and transport with controlled HTTP replies; no UI mocks.
import assert from 'node:assert/strict';
import ts from 'typescript';
import { mkdtempSync, readFileSync, writeFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
const dir = mkdtempSync(path.join(tmpdir(), 'dora-query-client-'));
let checks = 0;
try {
  for (const name of ['queryTypes','queryContract','queryTransport','queryApi']) {
    const src = readFileSync(new URL(`../src/services/${name}.ts`, import.meta.url), 'utf8');
    const out = ts.transpileModule(src, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext } }).outputText;
    writeFileSync(path.join(dir, `${name}.mjs`), out.replace(/from '(\.\/[^']+)'/g, "from '$1.mjs'"));
  }
  const { createKnowledgeApi } = await import(pathToFileURL(path.join(dir,'queryApi.mjs')));
  const { parsePacket, parseEvidence, parseDocument } = await import(pathToFileURL(path.join(dir,'queryContract.mjs')));
  const evidence = { evidenceId:'ev:1', contentHash:'hash1', sourceKind:'wiki', data:{title:'利润率',text:'原文'}, readAt:'2026-10-18', observedPeriod:{label:null,isoDate:null}, documentId:'wiki/1', documentVersion:1, snapshotId:null, archiveVersion:null };
  const packet = { contractVersion:'unified-query-v1-candidate', runId:'run/1', ok:false, status:'partial', question:'利润率', answer:'可用部分', evidence:[evidence], citations:[{evidenceId:'ev:1',contentHash:'hash1',href:'https://invalid.test'}], missingParts:['current'], sourceStates:[], clarifications:[], usage:{actualTokens:null,actualCost:null} };
  assert.equal(parsePacket(packet).status,'partial'); checks++;
  assert.equal(parsePacket({...packet,ok:true,status:'abstained',evidence:[],citations:[]}).status,'abstained'); checks++;
  const limited={...packet,status:'limited'};delete limited.clarifications;
  assert.equal(parsePacket(limited).status,'limited');checks++;
  for (const bad of [{...packet,contractVersion:'other'},{...packet,runId:null},{...packet,evidence:[{...evidence,evidenceId:null}]},{...packet,citations:[{evidenceId:'other',contentHash:'hash1'}]},{...packet,evidence:'oops'}]) {
    assert.throws(()=>parsePacket(bad)); checks++;
  }
  assert.equal(parseEvidence(evidence,{kind:'evidence',runId:'run/1',evidenceId:'ev:1',contentHash:'hash1'}).snapshotId,null); checks++;
  assert.throws(()=>parseEvidence({...evidence,contentHash:'wrong'},{kind:'evidence',runId:'run/1',evidenceId:'ev:1',contentHash:'hash1'})); checks++;
  let calls=[];
  const make = (reply,mode='http')=>createKnowledgeApi({base:'/api',mode,fetchImpl:async(url,init)=>{ calls.push({url,init}); return reply(); }});
  const response=(value,status=200)=>new Response(JSON.stringify(value),{status});
  const api=make(()=>response(packet));
  await api.answerQuestion({question:'利润率',includeSimulated:false});
  assert.equal(calls.length,1); assert.equal(calls[0].init.method,'POST'); checks++;
  calls=[]; await make(()=>response(evidence)).getRunEvidence({kind:'evidence',runId:'run/1',evidenceId:'ev:1',contentHash:'hash1'});
  assert.equal(calls[0].url,'/api/query/runs/run%2F1/evidence/ev%3A1'); checks++;
  for (const status of [404,409,422,503]) {
    calls=[];
    await assert.rejects(make(()=>response({detail:{reasonCode:'source_changed',runId:'r'}},status)).getWikiCard('a/b',3),e=>e.kind==='http'&&e.httpStatus===status&&e.reasonCode==='source_changed'&&e.runId==='r');
    assert.equal(calls.length,1); assert.equal(calls[0].url,'/api/wiki/cards/a%2Fb?version=3'); checks++;
  }
  await assert.rejects(make(()=>new Response('{')).answerQuestion({question:'q'}),e=>e.kind==='contract'); checks++;
  await assert.rejects(make(()=>new Response('<h1>Not deployed</h1>',{status:404})).answerQuestion({question:'q'}),e=>e.kind==='http'&&e.httpStatus===404); checks++;
  assert.equal(parseDocument({document:{id:'d',version:2,title:'历史',content:'原文'}},'d',2,'stored').version,2);checks++;
  assert.throws(()=>parseDocument({document:{id:'d',version:3,title:'最新版',content:'替换'}},'d',2,'stored'));checks++;
  assert.throws(()=>parseEvidence({...evidence,documentVersion:-1}));checks++;
  await assert.rejects(make(()=>{throw new TypeError('offline');}).answerQuestion({question:'q'}),e=>e.kind==='network'); checks++;
  calls=[]; await assert.rejects(make(()=>response(packet),'mock').answerQuestion({question:'q'}),e=>e.kind==='unavailable_mode'); assert.equal(calls.length,0); checks++;
  const { createQueryTransport } = await import(pathToFileURL(path.join(dir,'queryTransport.mjs')));
  const hanging = async(_url,{signal})=>new Promise((_r,reject)=>{ if(signal.aborted)reject(signal.reason); else signal.addEventListener('abort',()=>reject(signal.reason),{once:true}); });
  const transport=createQueryTransport({base:'/api',mode:'http',fetchImpl:hanging});
  await assert.rejects(transport.request('/test',{timeoutMs:5,parse:x=>x}),e=>e.kind==='timeout'); checks++;
  const ctrl=new AbortController(); const pending=transport.request('/test',{signal:ctrl.signal,timeoutMs:1000,parse:x=>x});ctrl.abort();
  await assert.rejects(pending,e=>e.kind==='cancelled'); checks++;
  const timeouts=[]; const original=globalThis.setTimeout;
  globalThis.setTimeout=(fn,ms,...args)=>{timeouts.push(ms);return original(fn,ms,...args);};
  try { await api.answerQuestion({question:'q'}); await api.searchKnowledge({query:'q'}); await make(()=>response(evidence)).getRunEvidence({kind:'evidence',runId:'r',evidenceId:'ev:1',contentHash:'hash1'}); }
  finally {globalThis.setTimeout=original;}
  assert.deepEqual(timeouts,[35000,20000,10000]); checks++;
  console.log(`PASS query client: ${checks} behavioral checks`);
} finally { rmSync(dir,{recursive:true,force:true}); }
