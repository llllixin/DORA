#!/usr/bin/env node
/**
 * 前端行为回归一键跑（`tools/cdp` 三个用例按序执行）。
 *
 * - 离线两例无需任何服务；在线例需 PG + uvicorn :8000，不在线会自行 SKIP（打印原因，不当成通过）。
 * - 任一用例红 → 本脚本退出码 1（可被归档前门禁复用）。
 *
 * 用法：node tools/cdp/run_all.mjs
 */
import { spawnSync } from 'node:child_process';
import { readdirSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const DIR = path.dirname(fileURLToPath(import.meta.url));
const cases = readdirSync(DIR).filter((f) => f.endsWith('_check.mjs')).sort();
const failed = [];

for (const file of cases) {
  console.log(`\n──────── ${file} ────────`);
  const r = spawnSync(process.execPath, [path.join(DIR, file)], { stdio: 'inherit', env: process.env });
  if (r.status !== 0) failed.push(file);
}

console.log(`\n===== run_all：${cases.length - failed.length}/${cases.length} 用例通过 =====`);
if (failed.length) {
  console.log(`❌ 失败用例：${failed.join(', ')}`);
  process.exitCode = 1;
} else {
  console.log('✅ 全部用例通过（在线用例若 SKIP，会在其输出里显式说明「未跑」）');
}
