## 1. 缓存模型与 Repository

- [x] 1.1 `models.py` 增 `InsightReasoning`（insight_id 唯一、semantics JSON、provider、generated_at），验证：init_db 后表存在
- [x] 1.2 `repository.py` 增 `get_reasoning/upsert_reasoning`（count 复用），验证：`python3 -c` upsert→get 往返一致

## 2. semantics 收编 + 刷新助手

- [x] 2.1 `app/reasoning/semantics.py::template_semantics` 迁移自引擎 `_semantics`；引擎改 import 别名；`TemplateProvider` 改为用 reasoning 包，验证：`reasoning_check` parity 仍通过（不再 import engine 私有函数）
- [x] 2.2 `app/reasoning/cache.py::refresh(repo, insights, provider)` 写入缓存并返回 {updated, fallback}，验证：`python3 -c` 对 9 条洞察 refresh 后行数=9

## 3. run_engine 合并缓存与标注

- [x] 3.1 run_engine 合并：命中缓存→覆盖 semantics + reasonSource/generatedAt；未命中→reasonSource=template（不加字段外内容），验证：`reasoning_check` 断言"refresh 后 /insights 项带 reasonSource/generatedAt 且 semantics 不变；清库后 reasonSource=template"
- [x] 3.2 `python3 -m tests.run_all` 全绿 + `npm run build`

## 4. 文档

- [x] 4.1 dev-log 迭代条目；路线图 V3-T2 标记完成；`docs/开发问题与经验.md` 记 D024（缓存合并语义与陈旧数据边界）
