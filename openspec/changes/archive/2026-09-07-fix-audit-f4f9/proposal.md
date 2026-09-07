# fix-audit-f4f9

## Why

docs/优化方向.md 审计问题收口：F4（sample 会覆盖 seed 档案的用户执行进度/验证记录）、F5（真实 LLM 路径无冒烟脚本）、F6（Watch 周期调度重启补跑语义未成文）、F7（前端无轻量刷新，跨端变化要手动刷新才可见）、F9（数字一致性核对未做）。F8（Chat 追问）是需规划的新能力，保留候选不动。

## What Changes

- **F4**：`seed_action_cases` 改为"档案缺失才建档"——sample/出厂重置**不再覆盖**已有 seed 档案的执行进度与验证记录（自建档案本就不动）；action_check 第 4 节结束后显式把 o1 复归基线，保证门禁可重复。
- **F5**：新增 `tests/llm_real_smoke.py`（可选：无 key 跳过；有 key 跑单条 + 全量 refresh 断言 9/9 llm），不进 run_all。
- **F6**：记录"重启丢失到期窗口、按 last_checked 补跑"为成文语义（D 系列）。
- **F7**：WatchPage/ActionPage 加 **20s 轻量轮询**（真实模式），先缓解"跨端变化不可见"；SSE/正式推送留阶段 2。
- **F9**：跑数字一致性核对（引擎 counts ↔ Pulse、9 洞察 evidence 全覆盖）并记录结论；新发现"洞察图表仍前端静态（data.ts charts）"单列 F11 候选。
- docs：docs/优化方向.md 状态更新、D032、dev-log 迭代 35。

## Capabilities

- 无 spec 变更（skip_specs）。

## Impact

- 后端：`seed.py`、`tests/action_check.py`、`tests/llm_real_smoke.py`（新）；前端：WatchPage/ActionPage 轮询。
- 验证：run_all 7 段 ALL GREEN（含重复执行可重现）；npm build；llm_real_smoke 无 key 时 skip。
