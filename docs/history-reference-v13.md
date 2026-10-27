# V13 历史工业五金全型号知识库与交互思维导图

基于既有历史档案整理的 **74 条历史条目**（而非 74 个真实可售 SKU），覆盖 5 类、27 个结构系列。锁具43、铰链9、拉手7、阻尼转轴14、其他1。拆分结构片段205条及历史规格/颜色/版本选项23条。所有记录统一标注“历史记录·未完成原件核验”。

## 文件
- `assets/history/history_reference_v13.json`：74 条历史参考，保存原描述、参数原文和待核信息。
- `src/ecom_images/history_reference_v13.py`：独立的历史商品参考表，不写入 V12 的 `catalog_skus` 表。
- `scripts/history_ref_admin.py`：初始化、预演、导入、搜索、完整性检查。
- `tests/test_history_reference_v13.py`：数量、重复导入、冲突回滚、无效核验状态等离线测试。
- 离线交互 HTML、完整 CSV、SVG/PNG 另见 V13 可视化合集。

## 使用步骤

已有库必须先备份；全新用户先运行 `python scripts/db_admin.py init`：

```bash
python scripts/db_admin.py backup --output backups/before-history-v13.sqlite3
python scripts/history_ref_admin.py init
python scripts/history_ref_admin.py import --dry-run
python scripts/history_ref_admin.py import
python scripts/history_ref_admin.py find --model MS705
python scripts/history_ref_admin.py check
```

旧库不删除、不覆盖已有表或真实 SKU。新导入只增加独立 `history_ref_*` 参考表；重复导入同一数据会跳过，发现修改冲突则拒绝覆盖。真实 SKU 的绑定要求原图纸或实物核验依据以及审核人，不能通过型号字符串相似度自动合并。

## 审核规则与限制

- MS731、MS828、MS830 每个后缀分别保留；LG 外观端头不是正式订货号。
- XAH18 与 HC-XAH18 可能是别名，但 **尚未核对，不自动合并**。
- 拉手 A/B 系列分别有 10/6 条孔距—总长配对，仅为历史规格对应关系，尚未映射店铺SKU。
- GL3-703-L 四种颜色、LS122 两种材质、CL226 胶套版均为历史变体候选；不能虚构库存。
- “结构片段”来自历史文字拆分，不构成精确 BOM、CAD 或工程设计验收。
- 原档案缺少完整逐条图片/原始技术图纸来源 ID；有明确历史数值不等于已经独立复核。
- SQLite 本机数据库不具备多用户审批权限或不可篡改审计，发布前还需人工核实。
