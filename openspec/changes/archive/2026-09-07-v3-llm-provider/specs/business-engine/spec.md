## ADDED Requirements

### Requirement: LLM 解释可配置且不污染判定
系统 SHALL 在 `DORA_REASONING_PROVIDER=llm` 时使用 OpenAI 兼容接口生成解释；生成结果的 `causeA/causeB` 数值与触发条件 SHALL 始终与引擎一致（LLM 仅允许改写可读文案），未配置 `DORA_LLM_API_KEY` 或调用失败时，对应洞察进入 `fallback` 且引擎输出不回退数据。

#### Scenario: 无 key 时刷新进入 fallback
- **WHEN** `DORA_REASONING_PROVIDER=llm` 且未配置 `DORA_LLM_API_KEY` 调用 `POST /api/reason/refresh`
- **THEN** 返回 `fallback` 覆盖全部洞察、`updated` 为空，且 `/api/insights` 语义仍为模板、判定数值不变

#### Scenario: LLM 只改文案不改数值
- **WHEN** 用确定性 provider mock 返回不同 `causeA.name/next`
- **THEN** 最终缓存 semantics 的 `causeA.value/causeB.value` 与引擎模板一致（数值稳定策略生效）

### Requirement: 数据变更后缓存失效
数据集上传/映射或出厂重置后，`insight_reasoning` SHALL 被清空，使旧解释不再命中。

#### Scenario: 重置样例后缓存清空
- **WHEN** 上传新数据或调用 `/api/datasets/sample`
- **THEN** `insight_reasoning` 行数为 0，后续 `/api/insights` 回退 `reasonSource=template`
