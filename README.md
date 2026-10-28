# huangren · 工业五金电商图批量制作工具

可运行的 **Python + Pillow** 图片自动排版脚本，适用于淘宝、天猫等电商平台的工业拉手、锁具、铰链、阻尼转轴等产品。支持单个配置制作多种图片，也支持按文件夹批量生成 SKU 图。

**核心原则：不编造产品结构、尺寸和卖点。** 所有产品图只做裁掉透明外边距、等比例缩放、居中叠合；不会用 AI 重画锁片、孔位、钥匙或改动原有尺寸标注。原始文件不覆盖。图片压缩可能产生轻微视觉差异，正式上架前必须人工核对。

## 生成模式

| 模式 | 尺寸 | 场景与约束 |
| --- | --- | --- |
| `search_white` | 1440×1440 | RGB 白底 JPG，小于 3MB；不添加文字、边框、阴影、Logo |
| `main` | 1440×1440 | 工业浅灰主图；产品与左侧文案分离；无四周边框 |
| `portrait` | 1440×1920 | 3:4 竖图；简洁背景，角落可选简短型号文字 |
| `sku` | 1440×1440 | 彩色标题+原产品/原尺寸图+用户填写的参数区 |
| `detail` | 800×1600 | 800px 宽单页详情模块；可增加多项真实卖点 |


## 🖥 中文可视化界面（运营助理优先使用）

除命令行外，本仓库已新增基于 Streamlit 的中文操作面板，无需改 JSON 就能上传多张实物图、选择淘宝/天猫或阿里国际站、选择主图/白底图/SKU/竖图/详情模块、填写真实文案、自动批量排版并下载 ZIP 和校验报告。

```bash
python -m pip install -r requirements-ui.txt
python -m streamlit run app.py
```

浏览器按终端提示访问本地界面（通常为 `http://localhost:8501`）。

面板按三个工作区组织功能：**素材制作**（主图策划、批量制图、SKU 审核、可选 AI）、**产品资料**（只读查询、SKU 档案、参数证据审核）、**竞品监测**（多 SKU 每日记录与价格变化报表）。左侧选择工作区和具体功能后，每次只显示一个页面。

星河跨境电商详情技能位于「素材制作」工作区，可在显式同意后调用第三方 AI 服务。需要自行提供有效 API Key，可能收费；真实图片与提示词会发送给第三方，不保证 AI 输出机械结构绝对一致。

详细操作说明见 [docs/web-ui.md](docs/web-ui.md)。

## 立即运行

先安装 Python 3.10+，然后在项目根目录：

```bash
python -m pip install -r requirements.txt
python scripts/create_demo_asset.py
python scripts/build_images.py --config configs/example.json --report output/report.json
```

生成图在 `output/`。**DEMO_only.png 是程序绘制的教学占位图，不是真实商品；严禁直接用于上架。**

### 替换为真实商品图

1. 将已抠图的透明 PNG（最好清晰的原始产品照片）放入 `assets/input/`。
2. 打开 `configs/example.json`，把 `source` 换为真实文件，例如 `assets/input/MS705.png`；将 `output`、`title`、`selling_points`、`specs` 改为真实信息。
3. 执行 `python scripts/build_images.py --config configs/example.json`。
4. 批量 SKU：执行 `python scripts/build_images.py --config configs/batch_sku.json`，它会读取 `assets/input/*.png` 并输出到 `output/sku/`。

如果标题是黄色色块，设置 `accent: "#F5C518"`、`title_color: "#000000"`。蓝色模板可用 `#0D7FF4`。品牌 Logo 仅在 `main`/`detail` 设置 `logo` 路径后显示；白底搜推图始终不加 Logo。

## 仓库结构

```text
huangren/
├── README.md
├── app.py                # 中文 Streamlit 界面
├── requirements-ui.txt   # 界面额外依赖
├── requirements.txt
├── .gitignore
├── configs/
│   ├── example.json
│   └── batch_sku.json
├── src/ecom_images/
│   ├── __init__.py
│   └── generator.py
├── scripts/
│   ├── build_images.py
│   └── create_demo_asset.py
├── tests/test_generator.py
├── docs/usage.md
└── assets/input/          # 放真实商品 PNG（不自动传到任何平台）
```

## 质量与合规说明

- **不失真**：等比例缩放，完整保留原产品及其已有标注；不做产品结构编辑。
- **纯白搜推图**：建议使用干净透明 PNG；若是非白底环境照片，脚本会拒绝直接生成，避免误认为已成功抠图。带内置阴影的原图需人工清理。
- **文案来源**：仅输出你在 JSON 中填写的内容。开孔尺寸、材质、盐雾/扭矩/寿命等不能凭模板推断。
- **格式检查**：输出后检查实际像素；搜推 JPG 额外验证白角和小于 3MB。JPEG 压缩画面内部可能有细微像素差异。
- **发布前**：仍需人工检查主体、细节、文字排版、画质和平台最新审核要求。

## 测试

```bash
python -m unittest discover -s tests -v
```

更多参数和注意事项见 [docs/usage.md](docs/usage.md)。


## 跨境电商详情 AI 技能（星河 4.0）

已安装用户上传的 **星河跨境电商详情4.0** 技能到 Codex 仓库级技能目录：`.agents/skills/xinghe-crossborder-detail-3/SKILL.md`。内含 20 篇参考规范、脚本、可选第三方 API 示例配置与使用说明。该 Skill 专注于跨境详情模块独立 AI 生图；上面介绍的本地 Pillow 排版工具继续负责淘宝/天猫主图、SKU 和白底素材。这是两种不同工作流程。

技能指令可以在仓库中被兼容的 Codex 智能体发现，但**不会仅因提交 GitHub 就自动连接 ChatGPT 或启动生成**。要实际通过星河接口生图，需要自行配置第三方 API 密钥；不得把 `.env` 或客户敏感图上传到公共仓库。

完整操作方法和命令见 [星河技能使用说明](docs/xinghe-skill.md)。


## 内置 Skills

### 1. 电商主图 Skill
- 路径：`.agents/skills/ecom-main-image-skill/SKILL.md`
- 作用：先分析商品信息与买家顾虑，再给出 3 个主图方向；确定方向后执行主图生成与自检。

### 2. 星河跨境电商详情 Skill
- 路径：`.agents/skills/xinghe-crossborder-detail-3/SKILL.md`
- 作用：用于跨境详情页、PDP、A+ 模块的 AI 视觉生成与页面规划。

## 主图方向策划（三选一，再出图）

中文网页的首个标签「主图方向策划」支持输入商品名、真实规格、已确认使用场景和买家顾虑，**一键输出 3 个方向，每个方向只含 1 个点击理由**。需手动选定方向后才能生成 1440×1440 的本地基础主图，也可以下载方向方案 JSON。详见 [中文界面说明](docs/web-ui.md)。这个功能是规则驱动的模板策划，不具备自动看图识别参数能力，不会虚构材质、检测数据或认证。

## Excel 批量 SKU 制图 V2.0

中文界面「③ Excel 批量 SKU」现在支持下载 [Excel 模板](assets/templates/sku_import_template.xlsx)、逐行填写 SKU 编码/图片名/型号/孔距/总长/材质/色块颜色，并与照片 ZIP 或多图上传做严格文件名匹配。一个 SKU 对应一张 1440×1440 JPG；不存在的图片、重复 SKU、异常参数逐行报错，不会替换成其他产品图。下载包附带逐行 CSV/JSON 报告和机器质量检查清单。

命令行也可以使用：

```bash
python scripts/build_sku_excel.py --excel /path/to/list.xlsx --images /path/to/photos.zip --out output/sku_all.zip
```

详细说明见 [Excel SKU 制图使用指南](docs/sku-excel-v2.md)。Excel 表格只提供数据模板，不会自动推断规格、计算孔距或创造未提供的产品结构。


## SKU 工业模板 V3 + 文档知识规范

V3 增加三种固定工业风：蓝白工业参数风、黄黑工业风、灰白极简技术风；Excel 每行可指定独立的 `尺寸图文件名`，将真实产品和原尺寸图分别等比例嵌入 1440×1440 的 SKU 模板，**不重新计算/绘制孔距或标注**。没有尺寸图时不臆造，缺指定文件时该行失败。

- 操作说明：[docs/sku-template-v3.md](docs/sku-template-v3.md)
- 学习资料提炼：[docs/knowledge-industrial-hardware.md](docs/knowledge-industrial-hardware.md)
- 模板文件：`assets/templates/sku_import_template_v3.xlsx`
- 代码：`src/ecom_images/sku_template_v3.py`

本功能为预设版式，不是任意参考图的像素级自动复制；上架前逐张人工复核尺寸、结构和材质。

## V4 自定义参考模板区域（运营助理）

在「③ Excel SKU / 工业模板 V4」选择「V4 自定义参考模板布局」，可上传参考 SKU 图进行**人工校准**：填写四个区域的 X、Y、宽、高（标题 / 原产品图 / 原尺寸图 / 参数表），保存 JSON 后批量复用，所有图片仍为 1440×1440 JPG。

- 参考图**只用于辅助定位**，不会自动擦除旧商品，也不会直接混入最终图。
- 若需要保留旧模板的背景装饰，须先在其他软件中将旧商品、旧文案和旧规格清除，上传 **1440×1440 净背景**并勾选确认。
- 产品和尺寸图等比例放置，既不重画标注，也不自动推算参数。参阅 [V4 说明](docs/sku-template-v4.md)。


## V5 模板库与人工审核

- Excel SKU 页面选择 **V4 自定义参考模板布局**，可在展开面板中用方向按钮（5/10/20/40px）微调四个区域，实时查看线框预览；也可用数字精确设定位置。当前未实现鼠标拖拽。
- 可保存多套 **本机 SKU 模板**，保存在 `.local/sku_templates/`（已被 Git 忽略），并加载、删除及导出 JSON。模板仅存布局，不含图片、密码或真实产品参数；在线临时主机不保证持久保存。
- 生成图片后，可在 **V5 逐张人工审核** 表中核对产品结构、原尺寸图、卖点和平台清晰度。必须四项确认才能标记“通过”；下载 ZIP 仅包含人工通过的图片及 CSV/JSON 审核报告。
- 审核结果是人员录入，并非程序具备识别机械孔位真伪的能力。完整使用指南：[docs/sku-review-v5.md](docs/sku-review-v5.md)。


## V6 Excel SKU 制图闭环：先检查、后制作、人工审核、记录追溯

V6 把原有 V2–V5 SKU 功能整理为四步：

1. **资料预检查**：检查 Excel 必填字段、重复 SKU、真实照片的文件名/完整性、原尺寸图及数值格式。只验证资料准备状态，不验证材质或性能真实性。
2. **批量制图**：仅在本批输入通过预检查后开启。允许用户明确选择“仅处理有效行”；生成的普通 ZIP 标为“内部制图包，未经审核”，不可直接发布。
3. **人工审核**：逐图勾选产品结构、原尺寸标注、卖点真实性及平台清晰度；返工必须写原因；编辑审核表后旧审核下载立即失效。
4. **保存与导出**：按图片 SHA256 绑定本批输出，保存审核摘要到 `.local/production_runs/`，明确通过的图片单独导出到 `approved/`；若图片内容或失败数量变化，则旧报告不能复用。

本机任务历史**只记录流水摘要与校验值，不存储商品原图和 API 密钥**，也不会上传到 GitHub。临时在线环境可能清空本机文件；想要留底必须自行备份通过审核的 ZIP。

详细说明：[V6 四步操作与审核说明](docs/sku-workflow-v6.md)。


## V7：全面检查及流程安全修复

已对 V6 代码进行离线检查，重点修复**预检查合格行与实际生成范围不一致、V2 尺寸图字段被忽略、AI 旧商品下载缓存**等问题，同时增强透明空图、返回图片和模板重名检查。

- 上传 SKU 时先进行当批预检查，只有本批获准行能够被执行；失败行保留在报告中。
- 有独立尺寸图的 SKU 必须使用支持该图层的 V3/V4/V5 模板，不再静默忽略。
- AI 生图页面更改商品图或提示词后，旧结果不再可下载。
- 自动检查只检验文件和规则，不证明实体参数、机械结构或平台审批通过。

详细审查问题、已修复项、限制和测试说明见 [仓库全面审查报告（V7）](docs/repository-audit-v7.md)。


## V8 — 离线端到端验收与星河 AI 下载安全加固

- 新增 `tests/test_realistic_workflow_v8.py`：用**模拟拉手**检查 Excel → 预检查 → SKU 制图 → 文件校验 → 模拟人工审核 → SHA256 留档 → 审核 ZIP。模拟审核不代表真实商品获得批准。
- 星河技能的 URL 图片下载仅允许 HTTPS 公网地址，逐级核查重定向、限制单图 12MB；base64 内容也有限额。
- 星河生图 ZIP 的图片扩展名按图像实际内容选择，不信任返回文件名。
- 若 SKU 使用原尺寸图，界面将提示**手机端小字可读性需要人工审核**，即使文件尺寸合格也不自动放行。
- 完整风险及测试范围：见 [V8 离线验收与安全报告](docs/test-and-security-v8.md)。未完成真实 Streamlit 浏览器与平台上架验收。


## V10 本机 SQLite 数据库（schema V2）

任务流水、SKU 模板、审核历史与导入指纹统一保存在 .local/huangren.sqlite3；数据库不保存商品原图或第三方 API 密钥，也不会自动跨电脑同步。V10 加强未知数据库拒绝接管、表/主外键检查、审核摘要语义校验、审核历史 SQL 保护、旧审核复核标记、只读健康检查及旧版备份迁移。

    python scripts/db_admin.py check
    python scripts/db_admin.py import-legacy --dry-run
    python scripts/db_admin.py import-legacy
    python scripts/db_admin.py backup --output backups/huangren.sqlite3
    python -m unittest discover -s tests -v

- 维护指南：[V10 数据库检查、迁移、备份与恢复](docs/database-v10.md)
- 本轮审查记录：[V10 数据库审查报告](docs/database-audit-v10.md)
- 历史指南保留：[V9 数据库说明](docs/database-v9.md)


## 数据库任务查询 V11（只读）

中文界面新增「⑤ 数据库运营查询（只读）」标签：按平台、任务阶段、UTC 日期和模板检索，分页展示历史任务，下载当前页 CSV，核对单个任务的审核事件摘要；不修改数据库。命令行使用 `python scripts/db_report.py summary` 或 `python scripts/db_report.py jobs --page 1 --format csv`。详细说明见 [V11 使用指南](docs/database-reporting-v11.md)。完整性与备份恢复仍使用 `scripts/db_admin.py`；不要把 SQLite 业务库、审核报表或图片上传到公开仓库。


## 数据库商品档案 V12（多店铺 / 商品 / SKU / 素材）

在 V10/V11 任务及审核数据库上，新增独立的商品档案表，支持**店铺 → 商品 → SKU → 素材摘要 → 制图任务关联**，保留旧任务数据且不自动推断 SKU 归属。中文界面第 ⑥ 标签支持下载 CSV 模板、先预演、确认后整批导入和按店铺检索。

```bash
# 运行旧数据库检查，正式扩表前备份数据库
python scripts/db_admin.py check
python scripts/db_admin.py backup --output backups/before-v12.sqlite3
# 增量初始化（不会删除旧表）
python scripts/catalog_admin.py init
python scripts/catalog_admin.py check
python scripts/catalog_admin.py template --output sku_catalog.csv
python scripts/catalog_admin.py import-csv --input sku_catalog.csv
# 仅在预演核对后执行写入
python scripts/catalog_admin.py import-csv --input sku_catalog.csv --apply
```

详见 [V12 数据库结构与完整指南](docs/database-catalog-v12.md) 和 [部署验收表](docs/database-v12-checklist.md)。数据库元数据不包含商品原图；本地 SQLite 不是多人权限平台。


## V13 知识库核心数据模型与证据闭环

在现有 V10/V12 SQLite 上增量增加制造商型号、显式 SKU 映射、原始资料指纹、参数主张、逐页证据定位、独立复核、冲突处理及状态历史。不会自动从 SKU 文本推断制造商型号；不会把原始文件字节存入数据库；证据、审核与状态事件采用追加式记录。

- 设计说明：[V13 核心数据模型与证据闭环](docs/database-knowledge-v13.md)
- 初始化：`python scripts/knowledge_admin_v13.py init`
- 检查：`python scripts/knowledge_admin_v13.py check`
- 统计：`python scripts/knowledge_admin_v13.py summary`
- 型号登记：`python scripts/knowledge_admin_v13.py add-model --code GL1-336 --category 阻尼转轴 --manufacturer "汇成五金"`
- 原始文件哈希登记：`python scripts/knowledge_admin_v13.py register-source-file --file "/path/to/catalog.pdf" --kind manufacturer_document --authority user_supplied`

V13 使用独立的 `knowledge_meta.schema_version=1`，不改变 V10 `PRAGMA user_version` 或 V12 `catalog_meta.schema_version`。初始化前备份 `.local/`。主张状态 `accepted` 仅表示通过数据库的证据/复核门槛，不等于产品获得认证。


## V13 文档导入与可追溯检索

在 V13 知识库上增量支持 PDF、DOCX、Markdown、TXT、XLSX、XLSM、XLS 的本地导入、文本索引、精确型号搜索和参数检索。PDF 结果包含 1-based 物理页码和文字行 bbox；Excel 返回工作表/单元格范围；Markdown/TXT 返回行号；DOCX 返回段落、表格行和标题路径。扫描 PDF 会标记缺少文字层，本版本不会声称 OCR 已完成。

```bash
python scripts/knowledge_ingest_v13.py init
python scripts/knowledge_ingest_v13.py import-file --file "资料/GL1-336产品目录.pdf" --kind manufacturer_document --authority user_supplied
python scripts/knowledge_ingest_v13.py search --model GL1-336 --attribute 扭矩
python scripts/knowledge_ingest_v13.py audit
```

详细说明见 [V13 文档导入、解析与证据定位](docs/database-knowledge-ingestion-v13.md)。原始资料默认存储在被 Git 忽略的 `.local/knowledge_sources/`；导入只建立来源索引，不自动生成已接受的参数主张，也不自动绑定同名 SKU 与制造商型号。旧版 Word `.doc` 需先另存为 `.docx`。


## V13 参数证据审核工作流

第四阶段已在 Streamlit 中文界面新增「⑦ 参数证据审核」页：可直接上传 PDF、DOCX、Markdown、TXT、XLSX/XLSM/XLS 原始资料，也可按型号/参数检索已导入资料；支持 PDF 页码与高亮区域、Markdown/TXT 行号、DOCX 段落/表格及 Excel 单元格定位。人工填写候选参数后原子创建待复核主张和来源证据，并支持追加复核、查看状态历史及处理未解决冲突。

~~~bash
python -m pip install -r requirements-ui.txt
streamlit run app.py
~~~

详细操作、证据门槛与限制见 [V13 参数证据审核工作流](docs/knowledge-evidence-review-v13.md)。系统不会自动接受参数或确认 SKU 映射；原始资料和 SQLite 数据库应在本地单独备份。

## 供应商资料提取示例

已将 DGDeler 阿里巴巴国际站主页整理为带来源链接的 Markdown 快照和 JSON，并另建跨来源核验补充。它们用于供应商背景检索，不作为具体产品参数或认证的权威证明：

- [供应商主页资料快照](docs/supplier-research/dgdeler_supplier_profile_2026-10-28.md)
- [结构化供应商资料 JSON](docs/supplier-research/dgdeler_supplier_profile_2026-10-28.json)
- [供应商交叉核验补充](docs/supplier-research/dgdeler_cross_source_verification_2026-10-28.md)
- [结构化交叉核验 JSON](docs/supplier-research/dgdeler_cross_source_verification_2026-10-28.json)

导入 V13 时建议将网页摘要标记为 other / unverified；产品级参数需回到具体产品页面、厂家规格书或检测报告核验。
### DGDeler 商品列表快照

已从阿里巴巴国际站商品列表第 1 页保存 16 条可见商品记录（仅当前页；页面显示分页 1/139，不推断全店商品总数）：

- [商品列表 Markdown](docs/supplier-research/dgdeler_product_list_page1_2026-10-28.md)
- [结构化 JSON](docs/supplier-research/dgdeler_product_list_page1_2026-10-28.json)
- [运营助理 CSV](docs/supplier-research/dgdeler_product_list_page1_2026-10-28.csv)

价格、MOQ 和可见销量是采集时页面展示值；标题中的技术描述均标记为未验证。

## 供应商商品目录采集与 SQLite 历史数据库

**模块化重构（第二阶段）**：供应商采集和 SQLite 代码已拆分为每文件不超过 300 行的模块；保留原有导入接口、SQL V1 表结构、V13 知识证据库与本地默认路径。详见 [模块拆分与兼容性验收](docs/supplier-research/supplier_module_refactor.md)。

**型号证据核对（第三阶段）**：新增只读型号/来源/SKU 关联报告、跨来源参数冲突检测，以及可选的制图前事实参数门禁。用 `python scripts/check_model_evidence_gate_v13.py --model-code GL1-336` 查看资料，门禁配置示例见 [型号证据门禁说明](docs/supplier-research/model-evidence-gate-v13.md)。未配置门禁的旧图片任务保持兼容。


- 全量采集操作说明：docs/supplier-research/dgdeler_full_catalog_capture.md
- SQLite 数据库结构、数据质量和运行流程：docs/supplier-research/supplier_catalog_database.md
- 本次云端采集受验证码限制的审计报告：docs/supplier-research/collection_run_2026-10-28.md
- GitHub Actions 全量采集工作流：.github/workflows/supplier-catalog-collection.yml
- V13 来源 URL 导入：scripts/import_supplier_capture_v13.py --include-reference-snapshots（可先导入现有 16 条商品列表快照和供应商主页摘要；商品详情 Markdown 会保存详情页 URL、采集方式和记录 ID）。
- 采集与覆盖状态说明：[DGDeler 全店采集工具](docs/supplier-research/dgdeler_full_catalog_capture.md)、[2026-10-28 采集审计](docs/supplier-research/collection_run_2026-10-28.md)。

采集器会保存每页检查点，提取可见规格表、JSON-LD、图片与 SKU 选项；SQLite 会保存商品、每次价格/MOQ/销量观察、详情属性、SKU 选项、采集批次及错误历史。使用 scripts/sync_supplier_catalog_db.py 同步与导出。GitHub Actions 将数据库、CSV、JSON 检查点和审计报告上传为 30 天 artifact，不会把动态数据库二进制直接提交到公开仓库。云端自动采集已验证会遇到 Alibaba 登录/验证码限制；要完成全量数据，请在 Windows PowerShell 中运行 scripts/run_full_supplier_capture.ps1，在打开的可见浏览器里手动完成站点验证，再查看完整性审计。工具不会绕过访问控制。供应商页面字段始终标记为待核验观察值，不会自动变成已接受技术参数。
