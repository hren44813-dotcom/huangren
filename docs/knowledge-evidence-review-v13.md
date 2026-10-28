# V13 参数证据审核工作流

## 启动

在仓库根目录安装界面依赖并启动本地应用：

~~~bash
python -m pip install -r requirements-ui.txt
streamlit run app.py
~~~

进入页面的「⑦ 参数证据审核」标签页。该页使用本机默认数据库 .local/huangren.sqlite3，不会把本地数据库或原始资料上传到 GitHub。

如果数据库不存在，先到「⑥ 商品 / SKU 档案」初始化商品档案；再回到「⑦ 参数证据审核」，点击「初始化 / 检查 V13 文档索引」。此操作只创建/验证已知版本的增量表，不清空 V10/V12/V13 历史记录。

## 导入资料

通过现有文档导入命令导入受控资料、供应商文件或内部资料：

~~~bash
python scripts/knowledge_ingest_v13.py import-file --file "资料/GL1-336产品目录.pdf" --kind manufacturer_document --authority user_supplied
python scripts/knowledge_ingest_v13.py import-file --file "资料/产品规格表.xlsx" --kind supplier_document --authority user_supplied
python scripts/knowledge_ingest_v13.py audit
~~~

原始文件存放在数据库同级的 knowledge_sources/ 目录。备份或迁移知识库时，需要一起备份 SQLite 数据库和这个目录。不要把用户私有图纸、原厂目录或数据库提交到公开仓库。

## 检索和建立候选主张

1. 输入精确制造商型号，可加「扭矩」「材质」「孔距」等参数关键词。
2. 在原始资料结果中核对文件名、SHA-256、来源等级、原文片段及定位信息。
3. PDF 片段可点击「校验原文件并显示 PDF 页图」。系统会重新计算原文件 SHA-256，匹配登记值后才渲染页面，并在已保存 bbox 上画出高亮框。
4. Markdown/TXT 显示原始行号和标题路径；Excel 显示工作表与单元格范围；DOCX 显示段落/表格行与标题路径。DOCX 不伪造固定页码。
5. 如没有精确制造商型号档案，必须由操作者显式登记型号、制造商（如已知）和类别；系统不会因 SKU 里出现同样的文字就建立型号映射。
6. 在候选表单中人工填写参数名称、原始值、单位、主张类型和录入人，并确认已核对原文。系统会在同一个 SQLite 事务中创建 proposed 主张和支持性来源证据。

候选主张创建后仍为 proposed（待复核），不会自动接受或直接用于工程/商品参数发布。

## 复核与接受门槛

复核队列展示参数主张、来源证据、复核历史和状态历史。复核时需填写审核人、角色、方法和说明。

接受主张必须满足现有 V13 数据库门槛：
- 至少一条支持性来源证据；
- 至少一条来自第二复核人、制造商或独立实验室的支持性复核；
- 不得存在反对性复核或反对性证据；
- 状态变化必须符合既有状态机。

如果尝试接受但未满足门槛，复核记录和状态事件会在同一事务中回滚。反对性复核会让已接受的主张重新进入 reopened（重新审查）状态。操作者的姓名/角色字段是人工录入信息；本地应用当前没有账号认证或权限隔离。

## 未解决冲突

页面会列出筛选范围内 open/reopened 的冲突，并并排显示两条主张的原始值。标记解决必须选取一个已登记来源、填写处理人及书面理由并确认已核对来源。冲突历史以 append-only 事件追加，不覆盖原主张或历史状态。

## 完整性与限制

- 原始资料片段创建证据、PDF 页图预览前都会校验存储文件 SHA-256 和文件大小；缺失或变化时拒绝操作。
- 片段文本是检索候选，不是自动生成的正确参数。来源等级是登记信息，不等于第三方认证。
- 扫描版 PDF 如果没有文字层，目前只会提示可能需要 OCR；本阶段没有实现 OCR。
- 不执行 Excel 公式、不自动测量图纸、不自动接受参数、不自动关联 SKU。
- PDF 页码是物理页码；印刷页码只有在证据中明确登记时才显示。
- SQLite 的 append-only 触发器用于防止常规 UPDATE/DELETE，不等于防篡改审计系统或身份权限系统。

## 测试

~~~bash
python -m unittest discover -s tests -p "test_knowledge_review_v13.py" -v
python -m unittest discover -s tests -p "test_knowledge_review_ui_v13.py" -v
python -m unittest discover -s tests -v
~~~

GitHub Actions 使用 Python 3.10 和 3.12 运行完整离线回归测试。
