## 1. LLM Provider

- [x] 1.1 `app/reasoning/llm.py`：`LLMProvider`（OpenAI 兼容 chat/completions；JSON-only；数值稳定合并），验证：无 key explain 抛错；`_merge` 单测：value 保持模板值、name/next 可改写、非法 next 回退
- [x] 1.2 `resolve_provider` 支持 `llm`（kind=llm）；未知 provider 仍抛错，验证：`resolve_provider('llm').kind=='llm'`

## 2. refresh 端点与失效

- [x] 2.1 `routers.py` 增 `POST /api/reason/refresh`（provider + updated/fallback），验证：无 key → fallback 全量、updated 空
- [x] 2.2 数据写入失效：upload/mapped/sample(seed) 后清空 `insight_reasoning`，验证：先 refresh 写入→再 sample→行数为 0 且 `/insights` reasonSource=template

## 3. 测试与文档

- [x] 3.1 `reasoning_check` 增 LLM 相关断言（未知 provider 用 'nope'；mock 数值稳定；无 key fallback），`python3 -m tests.run_all` 全绿 + `npm run build`
- [x] 3.2 dev-log 迭代 + 路线图 V3-T3 标记 + `docs/开发问题与经验.md` D025
