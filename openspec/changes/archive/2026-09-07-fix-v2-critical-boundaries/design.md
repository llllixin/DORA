## Context

见 proposal.md。修复源自 V2 边界审查探测（series-only-empty 误产 c2/o2、`<=` 未显式、证据硬编码时间、pulse 旧时间、前端静态文案）。

## Goals / Non-Goals

**Goals:** 引擎在无指标数据下静默；阈值语义函数化并有断言；时间动态化；前端名称下沉 + watching 标注静态。

**Non-Goals:** 不真实化 Watch/Action（V4）；不改图表展示层；不动归档结构与既有 spec。

## Decisions

- **空数据门禁放 run_engine**：`compute_snapshot` 保持可读（供诊断），`run_engine` 检测 `metric_series` 是否为空，空则返回零 pulse（`last_updated='--'`）与空 insights——一处收口，端点/evidence 天然生效。
- **规则函数**：`_below(actual, ref)`（`actual < ref`，margin streak 语义）；`_breach(actual, threshold, inclusive=True)`（默认 `<=`，east 升级）。`evaluate_signals` 改为调用函数；engine_check 加 4 条断言。
- **时间动态化**：pulse 的 `last_updated` 由 `snap.data_event.updated` 提供（无事件 → `'--'`）；`engine_evidence.updated` 由 Repository 最新事件生成（无事件 `'--'`）。
- **前端名称下沉**：`App` 把 `dataSrc.name · dataSrc.at 更新` 作为 `dataLabel` 传 PulsePage（默认旧文案做兼容）。
- **watching 标注**：在"持续关注"计数旁加 `?`（`title` 悬浮提示"当前为静态展示"），不动计数逻辑。

## Risks / Trade-offs

- 空数据门禁会改变"无 series 但存事件"时的表现 → 符合 spec，行为更稳。
- `evidence.updated` 现在取最近事件 HH:MM（日期用当天），与演示"09-06"文案略异 → 可接受（spec 要求取自更新事件）。
- 前端改动影响 Pulse 视觉 → 以 build + 冒烟回归兜底。
