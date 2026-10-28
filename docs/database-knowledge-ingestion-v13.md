# V13 文档导入、解析与证据定位

## 能力与边界

该模块在 V13 知识库上增加独立版本的文档索引表，不修改现有 V10/V12/V13 表、版本号或历史记录。支持 PDF、DOCX、Markdown、TXT、XLSX、XLSM 和旧版 XLS。旧版 Word .doc 需先另存为 .docx。

- PDF：按物理页码（从 1 开始）建立页面和文字行索引；行级区域保存 PDF 点坐标、页面尺寸和 0–1 归一化 bbox。可检索文字层；扫描页会提示“无可提取文字层”，本版本不执行 OCR。
- DOCX：保存段落编号、表格编号/行号、单元格位置和标题层级。DOCX 的实际分页受 Word、字体和打印设置影响，系统不会伪造页码。
- Markdown/TXT：保留原始行号；Markdown 另保留标题路径和章节片段。
- XLSX/XLSM/XLS：保留工作表、行号、单元格地址和单元格范围。公式只作为原文索引，不执行公式或重新计算。
- 原始资料保存在数据库同级目录下的 \`knowledge_sources/\`（默认数据库为 \`.local/huangren.sqlite3\`，因此资料位于被 Git 忽略的 \`.local/knowledge_sources/\`）。数据库只保存来源元数据、内容指纹、索引段及位置。
- SHA-256 用于检查字节是否变化；来源级别是登记时的声明，不是系统认证。导入内容只用于检索，不自动创建参数主张、接受工程参数或绑定 SKU/型号。

## 初始化和导入

先备份数据库和原始资料。确认 V12 商品档案已初始化后：

\`\`\`bash
python scripts/knowledge_ingest_v13.py init
python scripts/knowledge_ingest_v13.py import-file --file "资料/GL1-336产品目录.pdf" --kind manufacturer_document --authority user_supplied --document-family "GL1-336"
python scripts/knowledge_ingest_v13.py import-file --file "资料/竞品规格.xlsx" --kind supplier_document --authority user_supplied
python scripts/knowledge_ingest_v13.py import-file --file "资料/产品说明.docx" --kind manufacturer_document --authority user_supplied
python scripts/knowledge_ingest_v13.py summary
python scripts/knowledge_ingest_v13.py audit
\`\`\`

支持的资料类型：\`manufacturer_document\`、\`supplier_document\`、\`purchase_record\`、\`physical_photo\`、\`lab_report\`、\`platform_export\`、\`internal_note\`、\`other\`。默认最大文件 100 MiB；Office ZIP 解压体积、条目数量、表格行列和 PDF 页数也有限制。重复导入相同来源会复用已索引结果；相同 SHA-256 对应不同文件身份或来源级别时拒绝静默覆盖。

## 型号与参数检索

\`\`\`bash
# 按精确型号搜索；不会把 GL1-336-A 或 XGL1-336 当作 GL1-336
python scripts/knowledge_ingest_v13.py search --model GL1-336

# 型号 + 参数词；PDF 可返回原始页码及文字区域
python scripts/knowledge_ingest_v13.py search --model GL1-336 --attribute 扭矩

# 搜索原始资料与已有结构化参数主张
python scripts/knowledge_ingest_v13.py search --query "扭矩 6 N.m"
python scripts/knowledge_ingest_v13.py search --query "GL1-336 扭矩"

# 仅搜索已经登记的制造商型号
python scripts/knowledge_ingest_v13.py search-models --query GL1-336
\`\`\`

API：

\`\`\`python
from ecom_images.knowledge_ingest_v13 import import_document, search_knowledge, audit_document_store

result = import_document(
    file_path="资料/GL1-336产品目录.pdf",
    source_kind="manufacturer_document",
    authority_level="user_supplied",
)
matches = search_knowledge(model_code="GL1-336", attribute="扭矩")
audit = audit_document_store()
\`\`\`

每条文档检索结果包含来源 ID、文件名、SHA-256、来源类型/级别、片段文字和位置。PDF 的 \`location.pdf_page\` 是物理页码，\`location.region.bbox\` 是页面坐标，\`normalized_bbox\` 是归一化坐标；Excel 使用工作表和单元格范围；Markdown/TXT 使用行号；DOCX 使用段落/表格位置和标题路径。印刷页码只有人工录入证据时才会有值，系统不从模糊页脚猜测。

## 验证

\`\`\`bash
python -m unittest discover -s tests -p "test_knowledge_ingest_v13.py" -v
python scripts/knowledge_ingest_v13.py --database .local/huangren.sqlite3 audit
\`\`\`

审计会检查 SQLite 完整性、已索引源文件的 SHA-256、索引段数和每个索引文本段的 SHA-256。审计只读，不会自动修复或覆盖来源文件。
