## 1. 解析器

- [x] 1.1 新建 `app/watch/__init__.py` 与 `app/watch/parser.py`：`parse_watch_text(text) -> {ok, intent?, unsupported}`。TARGETS 有序词典（east_orders 先于 revenue/orders；含 returns dimension=""）；频率词/数字/中文数字/条件句式解析；unknown 拒绝；未识别条件给建议默认并标 `condition_defaulted`；验证：见 1.3 用例
- [x] 1.2 `schemas.py` 增 `WatchParseRequest(BaseModel)`（text）；`routers.py` 增 `POST /api/watch/parse`（纯文本，不触 DB）→ 返回 `parse_watch_text` 结果；验证：curl 支持句式返回 ok=true + intent、拒绝句式 ok=false + unsupported

## 2. 测试与收尾

- [x] 2.1 `tests/watch_check.py` 追加第 2 节「解析」：demo 句→east_orders/华东/streak_below days3；跌破 18% + 每天 09:00→below ref 18.0 ref_is_pct + daily 09:00；未知"库存周转"→ok=false unsupported；六建议 chips 中受支持 5 个 ok=true、库存周转拒绝；`python3 -m tests.watch_check` ALL GREEN
- [x] 2.2 回归：`python3 -m tests.run_all` **6 段 ALL GREEN**（golden 9 insights 不变）；端点 curl 冒烟
- [x] 2.3 dev-log「迭代 23」+ 路线图 §3B V4-T2 标记 + archive（【测试证据】+【反思】）

【测试证据】watch_check（第 1+2 节）→ "watch_check OK（第 1 节 领域 CRUD + 第 2 节 解析 全绿）"；run_all → ALL GREEN（6 段）；端点冒烟（绕代理 POST /api/watch/parse）：demo 句→ok=true+east_orders/华东/streak_below days3、跌破 18%+每日 09:00→below ref 18.0+ref_is_pct+daily、库存周转→ok=false+unsupported。
【反思】词典优先匹配必须有序（east_orders 先于 revenue，防"华东销售额"误入"销售额"）；dimension 只能给引擎口径明确的（returns 门店级→""，聚合口径 T3 定义，不硬造）；条件单语义 + breach 优先，避免过早支持复合条件；"建议默认条件"用 condition_defaulted 显式标记交确认界面，杜绝隐藏默认（延续 D029 诚实原则）。
