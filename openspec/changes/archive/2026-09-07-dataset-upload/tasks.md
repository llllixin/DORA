## 1. 后端入库（ingest + repository）

- [ ] 1.1 `requirements.txt` 增 `openpyxl`；安装验证：`pip install 'openpyxl==3.1.5'` 后 import 成功
- [ ] 1.2 `app/repository.py` 增 `replace_series(metric_keys, items)`（同事务删旧+插新），验证：`python3 -c` 对某 key 替换后 `get_series` 返回新值且旧值不再存在
- [ ] 1.3 新增 `app/ingest.py`：`parse_dataset(content, filename)`（csv 标准库 / xlsx openpyxl）+ 校验（表头齐全、metric_key 白名单、value 数值、非空），错误抛 `IngestValidationError`；验证：非法文件抛错、合法 CSV 解析出行数与内容一致
- [ ] 1.4 `routers.py` 增 `POST /api/datasets`、`POST /api/datasets/sample`、`GET /api/datasets/current`，并注册 400 handler；验证：curl 上传合法文件 200、非法文件 400、样例接口返回行数

## 2. 数据替换与引擎反映

- [ ] 2.1 上传成功后写入 `data_update_log`（updated=当前时间、rows_added、affected metrics），验证：`GET /api/datasets/current` 反映新事件
- [ ] 2.2 上传一组与种子不同的合法 margin 数据后 `/api/pulse`、`/api/insights?type=problem` 反映新值（引擎即时变化），验证：curl 对比上传前后 p1 metric/streak
- [ ] 2.3 新增 `backend/tests/ingest_check.py`：覆盖合法/非法/引擎反映/DB 离线 503 四类（可用 mock 不依赖真实上传文件），验证：`cd backend && python3 -m tests.ingest_check`

## 3. 前端接通冷启动入口

- [x] 3.1 `doraApi.ts` 增 `uploadDataset(file)` 与 `loadSampleDataset()`（FormData POST，三模式），验证：类型检查通过且 mock 分支返回原行为
- [x] 3.2 `OnboardingPage/DataSourcePicker/App`：非 mock 分支"载入样例"调真实接口、上传调真实接口并回写 `doraDataSource` + 触发同步；mock 分支不变，验证：`cd frontend && npm run build`
- [x] 3.3 端到端手工冒烟（后端运行）：上传样例→Pulse/Tab 计数由引擎驱动；上传自定义 margin 数据→p1 数值变化，验证：`python3 /tmp/dora_smoke.py` 仍全绿

## 4. 文档与看板

- [x] 4.1 `docs/开发过程记录.md` 追加迭代条目（含测试证据与反思）；`docs/版本路线图.md` 勾选 C3
- [x] 4.2 `backend/README.md` 补充上传 API 与格式说明；`docs/开发问题与经验.md` 记录新决策 D017（规范格式+openpyxl+事务替换；若 upload 揭示新坑则入 P 系列）
