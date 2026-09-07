# Dora · V3 Release Notes（Dora Reasoning）

> 发布日期：2026-09-07 ｜ 分支基线：`main` ｜ 验收：✅ sign-off（docs/V3_ACCEPTANCE_CHECKLIST.md）
> 一句话：**把"判断"保留在确定性引擎，把"解释文案"升级为可替换的 AI 生成层**——Provider 抽象 + 语义缓存 + LLM（OpenAI 兼容）+ 前端"重新解释"入口 + 金样本验收，未配 key 时全链路自动回退模板。

## 1. V3 交付（迭代 17–21，全部 OpenSpec 归档）
| 任务 | 交付 | 迭代 |
|---|---|---|
| T1 推理抽象层 | `app/reasoning/provider.py`：协议 + TemplateProvider（默认）+ `resolve_provider()` | 17 |
| T2 语义缓存 | `insight_reasoning` 表；`run_engine` 合并（命中覆盖 + `reasonSource/generatedAt`，未命中 template）；semantics 收编 reasoning 包 | 18 |
| T3 LLM Provider + 失效 | OpenAI 兼容 `LLMProvider`（JSON-only、**数值锁**：value 恒为引擎基线）；`POST /api/reason/refresh`；数据写入/出厂重置清缓存 | 19 |
| T4 前端入口 | 洞察详情来源徽标（AI/模板）+「↻ 重新解释」 | 20 |
| T5 验收收尾 | `golden_check` + `golden_baseline.json`（run_all 5 段）；验收清单 | 21 |

## 2. 架构（新增文本层）
```text
引擎判定（数字/触发/证据，永不来自 LLM）
   → run_engine 产出洞察（模板 semantics）
   → merge insight_reasoning 缓存（命中覆盖 + reasonSource/generatedAt，未命中 template 不写库）
   → /api/insights 输出给页面
   └ POST /api/reason/refresh（批量；无 key/失败→fallback 并保持模板）
Provider: template（默认）｜ llm（OpenAI 兼容，DORA_LLM_* 环境变量）
```

## 3. 配置与接口
- env：`DORA_REASONING_PROVIDER=template|llm`（默认 template，无 LLM 全绿）；`DORA_LLM_BASE_URL/API_KEY/MODEL`
- `POST /api/reason/refresh` → `{ok, updated, fallback, provider}`（幂等；无 key → updated=0 / fallback=N）
- 判定/evidence/规则端点行为与 V2 一致（V3 红线：LLM 只动文案）

## 4. 质量与验收
- **run_all 5 段**（engine / ingest / reasoning / golden / e2e）ALL GREEN ✅
- reasoning_check：parity 9 + 缓存合并 + **无 key fallback + 数值稳定 mock + 非法 next 回退**
- golden_check：模板模式 = V2/V3-template 基线（9 条洞察）
- 边界审查（B 组）：部分 provider 故障 → 7/2 回退；重复 refresh 幂等；空数据不崩；失败上传(400)不清缓存 ✅
- 人工验收 C 段 ✅ + sign-off（2026-09-07）

## 5. 已知问题（标注跟踪，不阻塞 V3）
> **LLM 批量刷新同步耗时有上界问题**：~~现状逐条 `timeout=40s`、同步顺序执行~~ → **阶段 1 已实施（迭代 27，change `llm-refresh-policy`）**：单条超时 10s + 整批预算 20s + 并发 3 + 熔断(3 失败/60s→开 30s) + 优先级(问题→机会→变化) + 并发单飞；实测真实 DeepSeek 9 条 **4.9s**（原串行 15.6s）。
> 兜底设计见 **docs/开发问题与经验.md · P011/D028/D030**。阶段 2（异步 job/SSE + 前端"更新中 n/m"）待后续立项。

## 6. 下一步
- **V4（Watch 真实委托）**：进入条件已满足（V3 验收通过）——看板 §3A.5。
- 或先做 **LLM 刷新兜底阶段 1**（纯后端，前端不变）。
