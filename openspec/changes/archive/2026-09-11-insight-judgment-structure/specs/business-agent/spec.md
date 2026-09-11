## ADDED Requirements

### Requirement: 问答流支持「后果」意图

系统 SHALL 在 `POST /api/dora/chat` 的意图识别中支持 `consequence` 意图（用户询问「后果/影响/不处理会怎样/风险」类问题），并在 `answer` 文本中产出**带固定前缀**的 `严重等级：` 与 `可能后果：` 段落；两段文本 SHALL 只由该洞察的引擎字段（`severity`/`consequence`/`desc`/`semantics`）组装，数字 SHALL 继续满足既有数字锁。未命中 `consequence` 关键词的问题，意图分类 SHALL 保持既有行为（`why`/`evidence`/`opportunity`/`delegate`/`handle`/`what`）不变。

#### Scenario: 问到后果时返回等级段与后果段
- **WHEN** 提交问题「这条洞察不处理会怎样？」并带对应 `insight_id`
- **THEN** `answer` 文本含 `严重等级：` 与 `可能后果：` 两段，其内容分别与该洞察的 `severity`、`consequence` 字段一致

#### Scenario: 段落前缀稳定可归位
- **WHEN** 前端按前缀把 `answer` 文本拆行归位（`严重等级：` / `可能后果：`）
- **THEN** 两段均可被逐个识别，且不与 `下一步建议：` / `可参考历史先例：` / `主要影响因素：` 段落内容重复

#### Scenario: 既有意图不受影响
- **WHEN** 提交「为什么利润率会失速？」或「证据是什么？」
- **THEN** `intent` 仍分别为 `why` / `evidence`，`answer` 文本结构与本需求引入前保持一致

#### Scenario: 数字锁继续成立
- **WHEN** 检查 `consequence` 意图下 `answer` 文本中出现的数字
- **THEN** 这些数字均出现在该洞察的引擎 payload（`metric`/`delta`/`confidence`/`desc`/`semantics`/`severity`/`consequence`）中
