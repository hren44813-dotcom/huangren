# V15 原始证据深度审查

## 本轮成果
- V13 的 74 条历史记录原样保留。
- 原始《汇成五金画册(1).pdf》共 195 页，原件大小 173,132,513 bytes，SHA-256 已对原始字节重新计算并匹配。
- 建立 87 条证据断言，覆盖 16 个经人工查看的 PDF 页，关联到 42 条历史档案；其中 35 条档案具有精确型号页码锚点。
- 精确型号列名、系列后缀、候选别名、图纸存在、尺寸表存在分别记录；不把任何目录证据升级为工程验证。
- 15 项本地单元测试通过；SQLite dry-run、正式导入、幂等重导入、冲突回滚、append-only 和完整性检查通过；HTML JS 语法检查通过。

## 原件身份
- 文件：汇成五金画册(1).pdf（用户文件库原件，不上传公共 GitHub）
- SHA-256：`13b025c578ae6d0f164843545d8d6539ed5c36861b5b2b061832ea69f2d360b2`
- PDF 页数：195；文件大小：173,132,513 bytes
- 印刷页码仅为辅助定位，优先使用 PDF 页索引。

## 当前计数
| 指标 | 数量 |
|---|---:|
| 历史档案 | 74 |
| 证据断言 | 87 |
| 精确型号列名断言 | 39 |
| 图纸存在断言 | 14 |
| 系列变体断言 | 32 |
| 候选别名 | 1 |
| 尺寸表存在（待双人复录） | 1 |
| 有精确型号页码锚点的历史档案 | 35 |
| 有任意证据锚点的历史档案 | 42 |
| 独立工程参数核实 | 0 |
| 已确认正式店铺 SKU | 0 |

## 关键消歧
- PDF第193页写作 `HC-XAH18`，而历史记录为 `XAH18`。它被记为候选别名，不能自动合并。
- PDF第55页出现 `CL219-1`，不能直接把它视为通用 `CL219` 的同一 SKU。
- `MS705-Z`、`MS705-S`、`MS705-3A/B/C/U` 分开保留；基础型号和后缀不得按字符串前缀自动合并。
- `MS866` 的索引页列出多个后缀；基础档案不代表这些具体 SKU 已核实。

## 证据边界
- 型号出现在画册中，不代表店铺实际在售或与实物完全一致。
- 图纸存在，不代表每个尺寸已双人复录或实测。
- 材料、扭矩、公差、盐雾、寿命、BOM、认证和店铺 SKU 映射仍未独立核实。
- 代码测试只能证明数据规则执行，不证明机械产品的物理属性真实。

## 复现
```bash
python -m unittest discover -s tests -p "test_evidence_registry_v15.py" -v
python src/ecom_images/evidence_registry_v15.py
python src/ecom_images/evidence_registry_v15.py db-init --database data/evidence_v15.sqlite3
python src/ecom_images/evidence_registry_v15.py db-import --database data/evidence_v15.sqlite3 --dry-run
python src/ecom_images/evidence_registry_v15.py db-import --database data/evidence_v15.sqlite3
python src/ecom_images/evidence_registry_v15.py db-check --database data/evidence_v15.sqlite3
```

V15 使用独立证据数据库，不直接改动正式 `catalog_skus`。历史快照、来源和断言采用 append-only；发生冲突时拒绝覆盖。
