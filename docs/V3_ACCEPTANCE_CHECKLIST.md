# Dora · V3（Dora Reasoning）验收与审查清单

> 对应：docs/历史版本路线.md §3A（V3 规划已归档）。完成 V3-T1..T5 后填写；自动项给出命令，人工项给出核对标准。
> 快照说明：本文为 V3 sign-off 验收记录（A/B/C 已确认，2026-09-07），**此后不再更新**；后续 backlog 见 `docs/持续优化路线.md`（文档职责分层见 `docs/文档地图.md`）。

## 审查状态（2026-09-07）
- **A · 自动门禁 ✅**：`tests/run_all` 5 段 **ALL GREEN**（engine / ingest / reasoning / golden / e2e）；`npm run build` ✅；`/tmp/dora_smoke.py` 全绿 ✅
- **B · 边界/极端审查 ✅**：
  - B1 无 key + `provider=llm` → `updated=0 / fallback=9`，引擎判定不变、cache rows=0
  - B2 部分 provider 失败 → `updated 7 / fallback 2`（不 all-or-nothing）；重复 refresh 幂等（rows=9 稳定）；空数据 refresh 不崩溃；LLM 输出极端（超长 next 回退模板、code-fence JSON 可解析、非法 JSON 抛错→fallback）；**数值锁**（causeA/B.value 恒为引擎基线）
  - B3 非法上传（400）后语义缓存**保留**（rows=9），仅成功入库才失效
- **C · 人工核对 ✅**：用户确认通过（2026-09-07）——功能项经构建产物与 API/模板模式验证 + 用户指令确认，见下方 Sign-off。
- **已知问题跟踪**：**LLM 批量刷新同步耗时上界问题**（现状逐条 40s、最坏 ≈360s）→ 分析与兜底设计见 **P011 / D028**；**状态 = 已记录设计、阶段 1（超时拆分+预算+熔断）待开工**；阶段 2（异步 job/SSE）随前端配合。判定与来源标注不受影响。

## A. 自动门禁（提交/验收前置）
- [x] `cd backend && python3 -m tests.run_all` → **ALL GREEN（5 段）**
  - engine_check：引擎判定回归
  - ingest_check：上传/映射入库回归
  - reasoning_check：parity + T2 缓存合并 + **T3 数值稳定/无 key fallback**
  - golden_check：模板模式输出与 V2/V3-template 基线一致（9 条洞察）
  - e2e_api_check：文档 4 个核心验收用例
- [x] `cd frontend && npm run build` 通过
- [x] 冒烟：`python3 /tmp/dora_smoke.py`（5173 代理、绕代理 env）3/2/4/4 全绿

## B. 红线审查（判定不被污染）
- [x] LLM mock 只改文案不改数字：`reasoning_check` 覆盖 causeA/B.value 锁引擎基线（命令同 A）
- [x] 触发/指标/证据/置信度逐字段不变：golden_check 快照含 trigger/metric/delta/factors/confidence/semantics
- [x] 数据写入/出厂重置后缓存失效（`/api/datasets`、`/datasets/mapped`、sample 后 `insight_reasoning`=0）

## C. 功能人工核对（需在运行界面确认）
- [x] 洞察详情显示来源徽标（模板解释 / AI 解释）
- [x] "↻ 重新解释"可用；template 模式 toast「✓ 解释已重新生成（模板模式）」
- [x] 配置 `DORA_REASONING_PROVIDER=llm` 且无 key 时：刷新返回 fallback、页面保持模板徽标与数据
- [x] （可选）配置真实 LLM key 后：徽标变「AI 解释」，数值/触发不变

## D. 收尾核对
- [x] dev-log 迭代、路线图 V3-T5 与版本状态、D 系列记录已同步
- [x] spec 导航（openspec/README、各能力 spec 需求来源表）已含 V3 新增条目
- [x] 大版本切换记录：V3 验收通过后把路线图版本速览标为 V3 已完成

## Sign-off
| 审查人 | 日期 | 结论（通过/待改） | 备注 |
|---|---|---|---|
| tomara（用户确认） | 2026-09-07 | 通过（V3 标为已完成） | 已知问题 P011/D028（LLM 刷新兜底阶段 1/2）标注跟踪，不阻塞 V3；C 段 UI 经构建产物+API/模板模式验证 |
