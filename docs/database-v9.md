# V9 SQLite 本地数据库：检查、迁移、备份和恢复

## 核心设计

旧版 V5–V8 使用 `.local/production_runs/*.json` 和 `.local/sku_templates/*.json`，文件散落、历史检索不便，在多个浏览器窗口同时改动时也容易覆盖记录。V9 新增 `src/ecom_images/database_v9.py`，并在中文界面中将任务和 SKU 布局模板的**新增保存**切换为 SQLite：

- 默认数据库：`.local/huangren.sqlite3`（已被 `.gitignore` 忽略）。
- 只保存任务编号、商品图文件名及 SHA256、预检查输入指纹、模板 JSON、人工审核摘要和事件历史；**不保存商品原图、账号密码、API Key、客户图纸**。
- 每次制图产生独立任务 ID；`jobs` 与 `job_files` 一对多，用户修改图片则必须产生新的任务记录。审核记录会留下追加历史，而不是覆盖上一次审核事件。
- 事务与外键约束：`BEGIN IMMEDIATE`、`PRAGMA foreign_keys=ON`、WAL 模式以及超时等待；过期的浏览器窗口通过 `revision` 版本检测拒绝覆盖。
- 已审核并不等于符合平台要求：仍需真人逐张核对孔位、尺寸、文字、性能数据和手机端清晰度。

## 数据表

| 表名 | 用途 | 重要限制 |
| --- | --- | --- |
| `jobs` | 制图任务、平台、模板、阶段、输入指纹 | 每任务 UUID 作为主键，核心字段创建后不可修改；有版本号 |
| `job_files` | 每张输出图的文件名和内容 SHA256 | 外键关联任务，不存图像本体，文件名防目录穿越 |
| `review_events` | 每次保存的人工作业审核摘要 | 追加历史、校验内容 SHA256，不是防篡改数字签名 |
| `templates` | SKU 模板名称及标准化布局 JSON | 忽略大小写防重名，最多 80 套 |
| `imported_files` | 已迁移的原 JSON 路径和原文件摘要 | 重复导入幂等，检测源文件后来是否被改动 |

数据库版本使用 SQLite 的 `PRAGMA user_version`；程序拒绝打开高于当前支持版本的数据库，防止旧程序回写破坏新格式。数据完整性检查同时运行 SQLite `integrity_check`、外键检查、任务-图片核对、模板 SHA256 验证与审核历史核对。

## 新用户启动

在仓库根目录执行：

```bash
python scripts/db_admin.py init
python scripts/db_admin.py check
python -m streamlit run app.py
```

`init` 会显式新建空数据库；`check` 本身不会因路径不存在而创建文件；本机保存的任务和模板不上传到 GitHub。Windows / macOS / Linux 均支持，SQLite 来自 Python 标准库，不需要额外数据库账号。

## 从旧 JSON 迁移（不删除源文件）

**迁移前先停止本机网页服务，并备份整个 `.local` 目录。** 然后执行：

```bash
python scripts/db_admin.py import-legacy --dry-run
python scripts/db_admin.py import-legacy
python scripts/db_admin.py check
```

默认只从 `.local/production_runs/` 和 `.local/sku_templates/` 读入，源 JSON 不删除、不修改。文件名、任务 ID、SHA256、字段及尺寸布局无效时会单独列出错误；单文件原子提交，其他可读文件不受影响。重复运行只会跳过相同来源和摘要的已导入文件，**不会偷偷覆盖**数据库任务。源文件导入后被手动修改，会提示冲突，需要人工检查。

如果旧版模板或任务保存在其他目录，可用 `--jobs <目录> --templates <目录>` 指定实际位置。`--dry-run` 返回 `would_import` 计数，并不写入旧业务记录。

## 安全备份

```bash
python scripts/db_admin.py check
python scripts/db_admin.py backup --output backups/huangren-20261027.sqlite3
```

通过 SQLite 在线备份 API 创建一致性快照，正确覆盖 WAL 未检查点的数据；不会使用直接复制主 `.sqlite3` 文件的方式。备份后再次校验 SQLite 和业务摘要。已存在的备份默认拒绝覆盖，需要用户显式使用 `--overwrite`。建议备份到受信任的加密硬盘或企业受控位置，不要直接上传公共 GitHub。

中文界面「③ Excel SKU」页面的数据库面板也提供**备份并下载**功能。数据包包含任务元数据和审核人标识，分享前仍应检查隐私。

## 恢复数据

**关闭所有 Streamlit、脚本或其他可能正在使用此数据库的进程**，保留一个单独的原始数据库备份，然后在仓库根目录执行：

```bash
python scripts/db_admin.py restore \
  --source backups/huangren-20261027.sqlite3 \
  --overwrite --app-stopped
python scripts/db_admin.py check
```

恢复操作拒绝在目标存在 SQLite `-wal` 或 `-shm` 文件时覆盖，防止覆盖正在使用的数据库。恢复内容在替换目标数据库之前会检查 SQLite 和业务摘要。数据库快照只包含元数据：无法从数据库恢复原始商品照片或已下载 ZIP，请另行保留原图与已审核成品。

## 测试和限制

```bash
python -m unittest discover -s tests -v
python -m compileall -q src scripts tests app.py
```

- 单机本地数据库而非云端多人审批平台，**没有登录权限、角色分级或防篡改审计签名**；直接有本机文件权限的人依然可以修改数据库。
- WAL 与乐观版本号改善同机并发，不能保证多台电脑实时同步；不要把正在写入的 SQLite 文件放入多个电脑同时写入的共享网盘。
- SQLite 数据保存了文件摘要，**并不自动检验长期存放在数据库之外的图片是否被替换**。上架审核导出时仍要拿实际图片和审核报告匹配。
- 旧 JSON 导入需用户显式运行命令；**不会在启动时自动删除、搬迁或覆盖旧数据**。V8 及早期 JSON 文件仍可留存作为恢复备份。
- 页面是否能在特定部署环境正确写入 `.local`，仍需目标电脑/主机实际启动验证；CI 只做无凭证离线自动测试。
