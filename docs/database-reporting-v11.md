# V11 数据库可视化查询与只读巡检

这一版仅增加**只读任务查询和运营报表**，不改变 V10 的 schema、审查流程、旧记录或业务数据库文件。SQLite 仍是本机元数据数据库，不存储商品原图或 API 密钥。

## 用途

1. 汇总任务、图片元数据、审核事件和模板数量。
2. 按状态、平台、UTC 创建日期、任务编号或模板名称分页搜索历史任务。
3. 核对单一任务的审核事件 SHA256，显示记录创建时间和审核人标识，不读取图片本身。
4. 导出**当前页** CSV（最多 100 条；网页每页 25 条），对 Excel 公式开头字符进行转义。

## 中文界面

```bash
python -m pip install -r requirements-ui.txt
python -m streamlit run app.py
```

打开「⑤ 数据库运营查询（只读）」标签。只读报表不会创建不存在的数据库，也不会在页面中直接修复数据库。这里显示的状态不等同于商品实际通过平台审查。

## 命令行

```bash
python scripts/db_report.py summary
python scripts/db_report.py jobs --stage '待人工审核' --page 1 --page-size 25
python scripts/db_report.py jobs --platform '淘宝 / 天猫' --since 2026-10-01 --until 2026-10-27 --format csv > jobs.csv
python scripts/db_report.py reviews <完整32位任务编号>
python scripts/db_admin.py check
```

命令行可在子命令**之前**指定 `--database /path/to/huangren.sqlite3`。`--since` 与 `--until` 采用数据库记录的 UTC 日期（闭区间）；筛选参数均通过 SQLite 绑定变量，不允许输入 SQL 语句。分页查询按 `created_utc DESC,id DESC` 排序，若**查询过程中有新任务写入**，相邻页的内容可能变化。报表是实时查询，不是固定快照。

CSV 带 UTF-8 BOM，适合 Excel 打开。敏感的商品文件名、模板名和审核人标识属于本地运营数据，导出后请放在受控位置，不要提交到公开 GitHub。报表不含原始图片，但仍可能包含业务信息。

## 安全边界

- SQLite 连接采用 URI `mode=ro` 与 `query_only=ON`。查询不会自动迁移、修复或新建数据库。
- 要求已存在的 V1/V2 业务表结构，拒绝不兼容 schema 与符号链接路径。
- 仅审查历史事件摘要的哈希，**不能替代**完整性扫描：`python scripts/db_admin.py check`。
- 只适合本地受信任的运营人员。Streamlit 没有账号和权限隔离，不能把该页面直接公开部署供任何人访问。
- V10 备份、迁移及恢复操作保持原来的管理命令，不会被 V11 报表调用。