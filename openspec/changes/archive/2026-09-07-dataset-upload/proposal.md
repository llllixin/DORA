## Why

V1 冷启动只有"载入内置样例"，上传仍是纯 Mock（只取文件名）；引擎数据源已落 PostgreSQL（C2），但没有"真实文件入库→引擎重算"的入口。C3 要打通"上传 xlsx/csv → 校验 → 落库（Repository）→ 引擎端点自动反映新数据"，让冷启动入口真正接上后端。

## What Changes

- 后端新增数据入库 API：
  - `POST /api/datasets`：multipart 上传 **CSV / XLSX**，内容须为"引擎输入规范格式"（每行 = metric_key/label/dimension/value/unit 的时序或单点行，支持 demo 全部指标 key 与门店/供应商维度）。
  - `POST /api/datasets/sample`：触发服务端幂等种子（等同 `python -m app.seed`），返回各表计数。
  - `GET /api/datasets/current`：当前数据源摘要（最近更新时间、新增行、受影响指标、各表行数）。
- 上传处理语义：
  - 解析失败 / 字段缺失 / 非法数值 → `400`（含错误详情）；DB 不可用仍走 `503`。
  - 合法文件**事务性替换**已覆盖指标 key 的系列（delete+insert within tx），并写入一条 `data_update_log`；随后引擎端点因按请求实时计算而自动反映新数据。
- 前端接冷启动入口（http/auto 模式）：`载入内置样例` 调 `POST /api/datasets/sample`；自定义上传调 `POST /api/datasets`，成功后回写 `doraDataSource` 并触发重同步。mock/离线仍走本地行为。
- 依赖：新增 `openpyxl`（xlsx 解析）；CSV 用标准库。

## Capabilities

### New Capabilities
- `data-ingest`: 经营数据文件上传与入库接口的对外行为——接受 CSV/XLSX 规范格式、校验、事务性写入 Repository 并触发引擎数据更新事件。

### Modified Capabilities
- `business-engine`: 上传/重载数据集后，引擎端点 SHALL 在不重启的情况下反映最新持久化数据（新数据 → pulse/insight 变化）。

## Impact

- 后端：新增 `backend/app/ingest.py`（解析/校验/入库）、`backend/app/routers.py` 增 `datasets` 路由、`backend/app/repository.py` 增 `replace_series`；`requirements.txt` 增 `openpyxl`；`backend/tests/` 增解析/入库校验脚本（engine_ingest_check）。
- 前端：`doraApi.ts` 增 `uploadDataset/loadSampleDataset`；`OnboardingPage/DataSourcePicker/App` 在非 mock 模式接真实接口（mock 回退保留）。
- 非目标（明确不做）：任意业务文件→指标口径的智能映射/字段映射向导（C4）；多 sheet 自动发现；上传的 Watch/调度触发（V4）；证据完全 DB 化（仍随 C3 一并把证据行改为读库或列入后置项——本 change 先完成数据入库主链路，证据 DB 化放入"收尾杂项"后置）。
