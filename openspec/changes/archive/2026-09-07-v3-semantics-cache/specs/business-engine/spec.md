## ADDED Requirements

### Requirement: 洞察语义可来自推理缓存并标注来源
系统 SHALL 将每条洞察的解释语义（semantics）与来源元数据（provider、generated_at）持久化于 `insight_reasoning`；引擎输出洞察时 SHALL 先读取缓存：命中则以缓存语义为准并给出 `reasonSource`/`generatedAt`，未命中则以模板语义回退并标 `reasonSource:"template"`。语义字段结构不得改变。

#### Scenario: 命中缓存的洞察携带来源标注
- **WHEN** 已为某洞察写入 reasoning 缓存后请求 `/api/insights`（或 `/api/insights/{id}`）
- **THEN** 该洞察 `semantics` 等于缓存内容，并带 `reasonSource` 与 `generatedAt`；结构与未命中时一致

#### Scenario: 未命中缓存回退模板且结构不变
- **WHEN** Repository 无该洞察 reasoning 缓存
- **THEN** 语义由模板生成、`reasonSource="template"`，且输出与 V2 基线逐字段一致
