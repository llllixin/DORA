## 1. 后端预览与映射校验

- [x] 1.1 `ingest.py` 导出 `read_rows(content, filename)`（扩展名+解析，不做值校验）与 `items_from_mapping(raw, mapping)`（白名单/列存在/数值/label 校验），验证：`python3 -c` 断言缺列/坏值抛 `IngestValidationError`
- [x] 1.2 `routers.py` 增 `POST /api/datasets/preview`（返回 columns+sampleRows）与 `POST /api/datasets/mapped`（multipart file + mapping JSON），复用大小/扩展名/400 语义，验证：curl preview 返回列与样例；mapped 成功入库并登记事件

## 2. 映射入库回归

- [x] 2.1 `tests/ingest_check.py` 增加映射用例：任意列布局（date/margin_value/region）映射为 margin 入库 → p1 反映新数据；缺列/坏值映射抛错，验证：`python3 -m tests.ingest_check`
- [x] 2.2 样例还原后引擎/自检仍绿，验证：`python3 -m tests.engine_check`

## 3. 前端映射步骤

- [x] 3.1 `doraApi` 增 `previewDataset(file)`/`mappedDataset(file, mapping)`（三模式；mock 返回 null/失败回退），验证：`cd frontend && npm run build`
- [x] 3.2 `DataSourcePicker`：在线分支选文件→预览列→紧凑映射表单（metric_key + value/label/dimension 列）→确认入库并回写；离线分支不变，验证：手工冒烟 + build

## 4. 文档与看板

- [x] 4.1 `docs/开发过程记录.md` 追加迭代（测试证据+反思）；`docs/版本路线图.md` 勾选 C4
- [x] 4.2 `backend/README.md` 增映射上传说明；`docs/开发问题与经验.md` 记 D018（映射字段集为单值列契约、非自动推断）
