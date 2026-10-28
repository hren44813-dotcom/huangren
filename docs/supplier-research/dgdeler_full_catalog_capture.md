# DGDeler 全店商品采集工具

此工具用于在本机可见浏览器中，逐页读取供应商公开商品列表并可选访问每个商品详情页。它不会绕过登录、验证码、访问控制或反爬限制；若网站要求验证，会暂停并要求操作人员手动完成。

## 安装

```powershell
python -m pip install -r requirements-supplier-capture.txt
python -m playwright install chromium
```

首次运行会打开独立的 Chromium 用户配置目录。请在浏览器里正常登录/完成网站要求的验证，然后返回终端按 Enter。不要把浏览器配置目录或登录凭据提交到 Git。

## 第一步：采集商品目录全部分页

```powershell
python scripts/seed_supplier_capture.py
python scripts/supplier_catalog_capture.py listing --max-pages 139 --delay 2.5 --refresh-existing
```

每一页都会保存检查点。输出默认在 `data/supplier_captures/dgdeler/`：

- `pages/page_001.json` 等：每页可见商品卡片、标题、链接、图片 URL、卡片文字和分类导航线索。
- `catalog.json`：去重后的总目录。
- `catalog.csv`：可用 Excel 打开的目录表。

如页面结构或分页按钮变化，工具会保留已有检查点并停止，不会伪造缺失页。再次运行会跳过已保存页的写入，但仍需通过页面导航到相应页。可先用 `--max-pages 2` 做小范围验证。

## 第二步：读取每个商品详情

```powershell
python scripts/supplier_catalog_capture.py details --delay 3
```

这会逐个访问目录中的商品详情页，提取页面标题、可见正文、规格表、定义列表、图片、meta 标签、JSON-LD 产品字段以及页面上可见的 SKU 选项控件。详情文本存入 `details/*.txt`，结构化字段存入 `details/*.json`。已经保存且有对应文本文件的详情会跳过；损坏或不完整的 JSON 会重新采集。首次建议先用 `--limit 10` 检查采集效果，再决定是否读取全目录。

详情采集结束后会生成：

- `details_index.csv`：每个商品一行，含 SKU/MPN/品牌/分类/价格/库存状态线索、图片数、属性数和采集状态。
- `detail_attributes.csv`：从规格表、定义列表及 JSON-LD `additionalProperty` 提取的字段-值长表，并保留页面行定位线索。
- `details_markdown/*.md`：带原始链接、采集时间、页面原文和“未经独立验证”标记的资料，可作为 V13 知识库来源。
- `details_audit.json`：检查详情缺失、损坏 JSON、缺失原文文件及是否完成。

## 第三步：检查采集完整性

```powershell
python scripts/supplier_catalog_capture.py audit
```

该命令会重建目录与详情导出，并输出 `catalog_audit.json` 和 `details_audit.json`。目录审计会对照页面实际显示的分页总数列出缺失页；详情审计会列出没有详情记录的商品。只有所有可见分页均已采集且详情记录/原文齐全时，才会报告 complete。提前使用 `--max-pages` 做小范围测试时，partial 是预期结果。

## 第四步：可选导入 V13 知识库

先预览将要导入的文件：

```powershell
python scripts/import_supplier_capture_v13.py --dry-run
```

确认目录无误后导入：

```powershell
python scripts/import_supplier_capture_v13.py
```

也可以先只导入 10 份：

```powershell
python scripts/import_supplier_capture_v13.py --limit 10
```

导入会将每个商品详情 Markdown 作为 `supplier_document`、`unverified` 来源保存到 V13 文档检索库。它不会自动创建或接受产品参数主张。若要使用非默认数据库，可通过 `--database` 指定路径。

## 重要限制

- 本机默认使用可见浏览器，以便你手动登录或完成网站要求的验证。自动化模式可使用 --headless --no-prompt，但不能完成交互式验证；检测到限制会停止并保留检查点。
- 商品页面可能要求登录、验证码或返回动态内容。必须按站点要求手动处理；如果持续被拦截，应停止并使用平台允许的导出/联系供应商获取目录，不要尝试规避。
- 商品标题中的材料、扭矩、尺寸、寿命等是卖家描述，必须保留来源并标记为待核验；不能自动当成已验证参数。
- 价格、MOQ、销量和交期是采集时页面显示值，可能变化；销量未显示应保留为空，不代表 0。
- 采集输出和浏览器 profile 是本地数据，不应提交到公开仓库。GitHub Actions 的自动采集结果会上传为 30 天 artifact；见 supplier_catalog_database.md。
