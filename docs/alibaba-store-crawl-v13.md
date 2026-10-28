# 阿里国际站店铺商品采集与 V13 导入

## 已知店铺导航

采集入口为 [Dongguan Dele Hardware Technology Co., Ltd.](https://dgdeler.en.alibaba.com/)。
当前已观察到的店铺导航包括：Hot sale products、Accessories、Hinge、Damping Hinge、Torque Hinge、Hasp、Lock、Lock cylinder、Plane lock、Handle、Ungrouped，以及 Company profile / Ratings & Reviews。采集器将这些已观察到的分类链接作为种子，再跟随页面中可见的同店分类、分页和商品详情链接。

## 运行

先在本机仓库初始化 V13 知识库（如果已经初始化，不会清空历史数据）：

~~~bash
python scripts/knowledge_ingest_v13.py --database .local/huangren.sqlite3 init
~~~

开始采集，保留原始 HTML、字段报告并写入 V13：

~~~bash
python scripts/alibaba_store_ingest_v13.py \
  --database .local/huangren.sqlite3 \
  --output-dir data/supplier_captures/alibaba_dgdeler \
  --max-pages 250 \
  --delay 1.5
~~~

仅采集并生成本地报告，不写数据库：

~~~bash
python scripts/alibaba_store_ingest_v13.py --no-import --max-pages 50 --delay 2
~~~

输出目录（已被 .gitignore 排除）：

- raw/：每个成功访问页面的 HTML 快照。
- derived/：每个商品详情页的字段证据 Markdown。
- crawl_report.json：访问状态、URL、来源 SHA-256、导入结果、被拦截/未访问页面。
- crawl_report.md：覆盖情况、访问阻断和缺失项摘要。
- products.json / products.csv：每个商品的型号、SKU/规格、材质、尺寸、MOQ、价格、表面处理、原文摘录及缺失项。

## V13 证据策略

- 原始 HTML 作为独立来源保存并索引；knowledge_sources.metadata_json 保留 source_url、规范化 URL、页面类型和采集方式。
- 商品字段报告作为 platform_export / system_export 派生记录导入，并标注其原始页面 URL 与 SHA-256。
- 所有来源默认标为 unverified。网页里提到的参数是供应商页面声明，不等于独立认证，也不会自动创建/接受 V13 参数主张。
- 字段提取仅识别页面明确展示的标签和值。未找到的 SKU、材质、尺寸、MOQ 等会列入缺失项；不会用其他型号的数据填补。
- HTML 行号是解析后的可见文本行，不是原始源码行；脚本和样式不会执行。
- 如果平台返回验证码、异常流量提示、HTTP 401/403/429/503 或跨域登录跳转，采集器会记录 URL 和原因，不尝试绕过。动态渲染但未出现在公开 HTML 中的 SKU 选项、图片文字和分页可能无法提取。
- 采集器使用请求间隔和页面大小限制。遇到限制时，应改用阿里国际站后台可导出的商品 Excel、产品详情 PDF 或浏览器保存的页面文件，再用 V13 导入流程补充。

## 测试

~~~bash
python -m unittest discover -s tests -p "test_alibaba_store_v13.py" -v
python -m unittest discover -s tests -v
~~~
