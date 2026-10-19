# Dora RAG 知识源

这里保存人工可读、可审核、可版本化的 RAG 源文件。`documents.json` 当前有 44 个主题、96 个文档版本；A02 追加44张受审卡片，原52版本完整保留。`ontology/` 是 32 个有类型概念、指标读取映射、歧义处理与有方向的一跳关系；不创建经营实例或替代引擎判断。生成的 chunk 和 embedding 只写数据库，可以随时重建。

默认本体为 reviewed 的 dora-ontology-v2；`releases/manifest.json` 固定内容 hash，v1 仅保留历史源，不能恢复旧错误别名做运行映射。修改已发布本体时发布新版本，禁止覆盖同版本内容。毛利/净利、退款率、SKU 种数等未绑定口径先澄清，华东订单读取 east_orders/华东。

`eval/questions.jsonl` 与 `judgments.jsonl` 保留原 40 题标准；运行评价默认使用 `ontology-v2` 的显式 q07/q08 澄清修订。用 `evaluate(service, profile="legacy-v1")` 可重现原标准在新代码下的差异，不能把它说成原门槛仍全部通过。

维护规则：

1. 一篇文档只说明一个主题；修改口径时增加 `version`，不要覆盖历史版本。
2. 只有 `status=reviewed` 且在有效期内的文档可进入默认索引。
3. 项目资料填写 `source_ref`；外部资料填写 `source_url`；模拟案例必须使用 `source_type=simulated`。
4. 当前经营数值不写入 Wiki，必须由业务工具读取。
5. 纯语义检查：`cd backend && python -m tests.ontology_check`、`python -m tests.ontology_integration_check`。`tests.rag_check` 会写库与 HTTP，必须使用隔离数据库。

首批资料是依据当前代码和主 Spec 编写的学习语料，不是企业真实经营案例。


## Wiki 与人工治理

[Wiki目录](wiki/index.md)从documents.json确定性生成，禁止与正式JSON分别修改。10张指标/集合卡、8条规则卡、9张SOP、17张模拟案例；新记录schema_version=2。正文/来源/适用范围/证据等级都参与审核payload hash。仅[legacy清单](legacy-release-manifest.json)中的固定52行可按旧格式读；新增或修改记录不能省略新字段绕过审核。

归档和lesson仍在原知识库展示；同事务生成独立draft候选。候选失败使归档回滚。模拟保持simulated；其他缺历史验证证据的记录标reported。actor是可信本机操作者记录，不是身份认证；A02不新增verified_case。

本机命令在backend目录运行（使用正确的DATABASE_URL，后端启动会建新表）：

```sh
python -m app.wiki.cli candidate-list
python -m app.wiki.cli candidate-collect
python -m app.wiki.cli candidate-review --candidate-id CANDIDATE_ID --decision approve --actor YOUR_NAME --reason REVIEW_REASON --base-version 0
python -m app.wiki.cli candidate-publish --candidate-id CANDIDATE_ID --wiki-dir ../knowledge/wiki
```

先检查完整来源、适用范围和实际已发布基版；--base-version不是随意填的默认值。candidate-collect是显式采集旧处理记录，不会在启动时自动将旧资料审成正式知识。candidate-revise --input FILE生成新draft修订，旧批准不能沿用。拒审使用decision=reject，仍为draft且记录理由。

撤销已发布候选：candidate-review使用decision=retire与当前正式基版，再candidate-publish显式发布退役标记；来源删除后仍可撤销，但不能再发布新的受审核事实。退役不删除原文；draft不屏蔽已审核旧版，retired在同步索引后阻断旧版回退。重新发布需新修订/版本和批准。新读接口只有GET /api/wiki/cards（含按ID/version读取）与GET /api/wiki/candidates；没有HTTP发布写接口。

源发布、Markdown投影、检索索引分别报告。CLI publish不会自动索引；索引同步使用已有POST /api/rag/index或正常后端启动。查询时跨日有效期、未同步退役传播、索引同版不可变和付费embedding去重由A06处理。本轮只同步隔离测试库。

第一批来源原文按审核hash保存于wiki/sources（.txt为代码/契约资料，不是经营快照），定位清单随A02归档保留。JSON中的governance保存审核hash/来源hash；历史定义不要求当前代码字节与旧hash相等。企业未知项保留，读到来源不代表企业成效验证。

## 本轮验收范围

固定40题Hit@5/引用/拒答/澄清检查通过，MRR从1.00降为0.896；离线上下文正文平均字符从215增加到1276，p95从450到1997。字符数不是Token，也不含完整模型请求。hash/template外部模型调用0，实际Token/费用未知；排序与上下文压缩继续交A06。

`python -m tests.wiki_check`、`wiki_candidate_check`、`wiki_integration_check`使用临时文件/SQLite与只读HTTP边界。完整PG/HTTP门禁`python -m tests.wiki_gate`只接受显式本地dora_a02测试库和API地址，含写入与seed，不能用业务库。无新前端Wiki页面，页面接入属于A08。
