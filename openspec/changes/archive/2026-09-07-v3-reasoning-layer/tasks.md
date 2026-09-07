## 1. 推理抽象层

- [x] 1.1 新增 `app/reasoning/__init__.py` 与 `provider.py`（Context/Result/Protocol/TemplateProvider/resolve_provider），验证：import 成功且默认解析为 TemplateProvider
- [x] 1.2 `backend/.env.example` 追加 `DORA_REASONING_PROVIDER=template` 注释，验证：env 缺省时 resolve 仍为 template

## 2. Parity 测试与回归

- [x] 2.1 新增 `tests/reasoning_check.py`：seed 后对全部引擎洞察做 parity（TemplateProvider==引擎 semantics）+ 未知 provider 抛错，验证：`cd backend && python3 -m tests.reasoning_check`
- [x] 2.2 `python3 -m tests.run_all` 全绿（引擎行为零变化）+ `npm run build` 绿

## 3. 文档

- [x] 3.1 dev-log 迭代条目；路线图 V3-T1 标记完成；`docs/开发问题与经验.md` 记 D023（T1 交付形态与 T2 接线边界）
