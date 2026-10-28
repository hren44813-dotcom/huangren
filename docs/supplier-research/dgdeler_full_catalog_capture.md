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
python scripts/supplier_catalog_capture.py listing --max-pages 139 --delay 2.5
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

这会逐个访问目录中的商品详情页，提取页面标题、可见正文、规格表行、图片 URL 和页面链接。详情文本存入 `details/*.txt`，结构化字段存入 `details/*.json`。已经存在的详情文件会跳过。首次建议先用 `--limit 10` 检查采集效果，再决定是否读取全目录。

## 重要限制

- 当前对话里的浏览器读取接口是只读的，不能代替你点击 139 页分页；本工具需要在你本机的可见浏览器中运行。
- 商品页面可能要求登录、验证码或返回动态内容。必须按站点要求手动处理；如果持续被拦截，应停止并使用平台允许的导出/联系供应商获取目录，不要尝试规避。
- 商品标题中的材料、扭矩、尺寸、寿命等是卖家描述，必须保留来源并标记为待核验；不能自动当成已验证参数。
- 价格、MOQ、销量和交期是采集时页面显示值，可能变化；销量未显示应保留为空，不代表 0。
- 采集输出和浏览器 profile 是本地数据，不应提交到公开仓库。
