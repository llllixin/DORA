## Context

见 proposal.md - Why。现状：Repository 已提供系列 upsert/读取（C2），引擎按请求实时计算；上传目前只存在前端 Mock。依赖：pandas/openpyxl 均未装。

## Goals / Non-Goals

**Goals:**
- 提供可被前端/API 客户端调用的入库端点（上传/样例/当前摘要）。
- 规范格式解析（CSV 标准库、XLSX openpyxl），校验失败 400、DB 挂 503。
- 事务性替换指标系列并登记更新事件；引擎即时反映。

**Non-Goals:** 任意口径文件自动映射/向导（C4）；多 sheet 探测；调度触发（V4）；证据行 DB 化（后置收尾项，本 change 不动）。

## Decisions

- **"引擎输入规范格式"为首版契约**：表头 `metric_key,label,dimension,value,unit`，每行即一条 series 点；支持 demo 的 8 个指标 key。选它因为与 Repository 模型一一对应、无歧义；"好看的上传体验/口径向导"属于 C4。
- **解析**：`.csv` 用 `csv.DictReader`（零依赖）；`.xlsx` 用 `openpyxl`（新增依赖，纯 Python 兼容 Py3.14）。不引 pandas（体积/版本风险大，当前不需要）。
- **写入语义**：在同一事务内对该文件出现的 `metric_key` 执行"删旧+插新"（`Repository.replace_series(keys, items)`），再 upsert `data_update_log`（updated=当前时间 HH:MM、rows_added=文件行数、affected metrics=文件出现的 keys）。保证要么全成功要么全回滚。
- **注册**：路由层校验扩展名与大小上限（如 10MB）后交给 `ingest.parse_and_validate`；业务校验（key 白名单、数值可转 float、行列完整性）在 parse 层完成并抛 `IngestValidationError` → 400 handler。
- **前端**：`doraApi.uploadDataset(file)/loadSampleDataset()` 走三模式封装（auto：HTTP 优先、失败回退本地模拟）；`OnboardingPage/DataSourcePicker/App` 在非 mock 分支调真实接口，成功回写 `doraDataSource` 并触发同步。
- **样例服务端化**：`POST /api/datasets/sample` 直接调用 `app.seed.run_seed()`，前端样例入口改为调它（数据真正来自服务端种子）。

## Risks / Trade-offs

- 规范格式限制真实文件形态 → 接受；通用文件映射在 C4 演进。
- openpyxl 解析大文件较慢 → 限制 10MB + 行数上限（如 5 万行）返回 400/413 可读错误。
- 替换 series 会覆盖演示数据 → 属预期（上传语义即"换数据源"）；样例接口可一键还原。
- 前端 auto 模式在无后端时回退 mock，需保证回退行为与现状一致（防回归）。

## Migration Plan

- 纯新增端点与字段，无破坏性变更；前端仅在非 mock 分支走真实接口。
- 回滚：单提交 revert 即可；DB 数据可通过 `POST /api/datasets/sample` 或 `python -m app.seed` 还原。
