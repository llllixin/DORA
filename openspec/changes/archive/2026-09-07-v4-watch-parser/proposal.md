# v4-watch-parser

## Why

V4-T1 建好了 watch_target/watch_event 持久化，但"一句话委托"还是人肉翻译。T2 把中文委托语句解析成结构化 intent（metric_key/dimension/condition/frequency），并暴露 `POST /api/watch/parse` 供前端"委托确认"回显（D029：规则词典 + 显式确认，**不接 LLM 判定**）。unknown 指标显式拒绝并给提示，不静默兜底。

## What Changes

- 新增 `app/watch/parser.py`：`parse_watch_text(text) -> {ok, intent?, unsupported[]}`。
  - **指标词典**：引擎支持的 metric key × 中文别名 × 默认维度 × 显示名（margin 利润率/全国、east_orders 华东销售额/华东、new_sku 新品增长/全区域、returns 退货率/空=整表、orders/revenue/aov/high_value）。
  - **条件句式**：连续 N 天（下降/上涨）+ 跌破/低于/超过/高于 X(%)；未识别时给"建议默认 连续 3 天下降"并标记 `condition_defaulted`（确认步可见，不做隐藏默认）。
  - **频率词**：数据更新时/实时→on_update、每日/每天→daily 09:00、每周→weekly；未提则 null。
  - **拒绝**：匹配不到任何指标别名（如"库存周转"）→ ok=false + unsupported 段。
- `POST /api/watch/parse`（body `{text}`，Pydantic `WatchParseRequest`）：返回上述结构；纯文本解析不触 DB。
- `tests/watch_check.py` 追加第 2 节「解析」用例（支持句式/频率/拒绝句式/六建议 chips 映射）；`run_all` 段不变（仍 6 段，watch_check 内部递增）。

## Capabilities

### Modified Capabilities
- `business-watch`: 委托语句可被解析为结构化委托（受支持指标/条件/频率），无法识别时显式拒绝；建议词与解析结果一致，供"确认→创建"使用。

## Impact

- 后端：`app/watch/__init__.py`（新包）、`app/watch/parser.py`、`schemas.py`（+WatchParseRequest）、`routers.py`（+端点）、`tests/watch_check.py`。
- 不改：引擎判定、Repository、前端（T4 接线）、既有 run_all 段。
- 验证：watch_check 第 2 节全绿；`curl -X POST :8000/api/watch/parse` 支持/拒绝句式 JSON 冒烟；run_all 6 段 ALL GREEN。
