# V13 型号资料核对与商品内容证据门禁

## 目的

本工具把已有 V13 制造商型号、SKU 映射、来源资料、原文片段、参数主张和复核记录组合成只读核对报告。它不替代人工审阅，也不自动把供应商网页中的文本提升为已验证参数。

**不会新增或迁移数据库表。** 工具以只读方式访问 V9/V12/V13 与文档索引，保持已有 SQLite 记录及其追加式事件历史不变。

## 工作流程

1. 登记制造商及精确型号；同型号代码如果对应多个制造商，查询不指定制造商时会被视为身份歧义。
2. 将图册、说明书、供应商页面或平台导出导入 V13 文档索引。每条来源保留 SHA-256、文件元数据及页码/行号/表格单元格等定位。
3. 先查看型号的原文命中与 SKU 候选。SKU 自由文本与型号相同只表示候选，不会自动创建关联。
4. 通过 \`link_sku_model\` 建立候选映射，再由人工使用来源 ID 和说明显式确认；映射到多个型号会阻止 SKU 内容门禁。
5. 将具体参数从原文片段创建为 \`proposed\` 主张；独立复核后才能尝试转为 \`accepted\`。
6. 核对报告对同一型号及其已确认 SKU 的活动主张进行比较。不同标准化值或单位会产生“待人工解决”的潜在冲突，不自动换算单位，也不自动挑选某个来源。
7. 只有通过证据门禁的参数才可以绑定到制图配置的具体文字字段。文案与已审核的值或单位不一致时，制图会在写出图片前失败。

门禁每次执行都会重新核验原始资料文件的 SHA-256 与文件大小；如果证据引用了索引片段，还会复核片段文本指纹、来源 ID 与原文摘录。审核后原始文件被替换、删除或损坏时，门禁会阻止制图。

## 查询型号资料与冲突

只读核对：

\`\`\`powershell
python scripts/check_model_evidence_gate_v13.py --model-code GL1-336
\`\`\`

限定制造商：

\`\`\`powershell
python scripts/check_model_evidence_gate_v13.py --model-code GL1-336 --manufacturer "制造商名称"
\`\`\`

查看某参数能否用于商品文案：

\`\`\`powershell
python scripts/check_model_evidence_gate_v13.py --model-code GL1-336 --require-attribute Torque
\`\`\`

检查一个店铺 SKU 是否已完成显式映射，同时核验参数：

\`\`\`powershell
python scripts/check_model_evidence_gate_v13.py --model-code GL1-336 --sku-id "<catalog_skus.id>" --require-attribute Torque
\`\`\`

命令输出 JSON。只读查询返回 0；内容门禁被阻止返回 2；数据库/参数/结构错误返回 1。退出码 0 只代表查询命令成功，若使用 \`--require-attribute\`，还需检查 \`allowed: true\`。

## 将证据门禁绑定到图片任务

在 \`configs/*.json\` 中，只有显式配置 \`evidence_gate\` 的任务才会启用此门禁；没有该字段的旧配置保持原有行为。示例：

\`\`\`json
{
  "mode": "sku",
  "source": "data/products/GL1-336.png",
  "output": "output/GL1-336-sku.png",
  "title": "GL1-336",
  "specs": [
    { "label": "Torque", "value": "6 N.m" }
  ],
  "evidence_gate": {
    "database": ".local/huangren.sqlite3",
    "model_code": "GL1-336",
    "manufacturer_name": "制造商名称",
    "sku_id": "来自 catalog_skus.id 的 SKU ID",
    "bindings": [
      { "field": "specs[0].value", "attribute": "Torque" }
    ]
  }
}
\`\`\`

支持的绑定字段：

- \`title\`、\`subtitle\`、\`label\`
- \`selling_points[0]\`、\`selling_points[1]\` 等
- \`specs[0].value\`、\`specs[1].value\` 等；规格的 \`label\` 必须与声明的参数名称一致

绑定中的每个参数都必须具有可用的 accepted 主张、可定位的支持性来源、第二复核人/制造商/独立实验室的支持性复核，并且不存在活动冲突或反对性记录。SKU 任务还要求型号映射已显式确认且映射来源级别足够。

如果文本里写了“8 N.m”，但已审核主张是“6 N.m”，即使数据库中存在已审核的 6 N.m，制图仍会被阻止。它不会自动替用户改写营销文案。

## 安全边界

- \`unverified\` 供应商网页可以进入来源库并用于人工核对，但不能单独作为商品技术参数的合格支持证据。
- “有原文命中”不等于“参数已审核”；来源搜索不会自动 OCR、解释或接受未登记的技术参数。
- 冲突检测覆盖数据库中已登记的活动主张。它不会凭空推断未被录入为主张的所有原文参数；新来源导入后，运营/工程人员仍需逐项复核可能相关的参数。
- 型号、SKU、系列变体和候选别名严格区分；任何精确型号或商业 SKU 关系都需要显式证据和人工确认。
- 图片任务的门禁只核验 \`bindings\` 中明确声明的字段。配置作者必须把每一项事实性参数文案绑定到对应属性；未绑定的其它营销文案仍需人工检查。
- 不改变已有 V13 数据、不自动解决冲突、不自动修改 SKU 关联，也不宣称已完成阿里巴巴全量商品采集。
