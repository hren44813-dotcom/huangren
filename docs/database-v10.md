# huangren 数据库 V10：完整性、迁移、备份与恢复

代码模块保留历史兼容路径 src/ecom_images/database_v9.py；V10 指本次功能加固版本，SQLite PRAGMA user_version=2 指数据库结构版本。

## 本轮重点
- SQLite schema 从版本 1 升至 2，已有 V1 库在下一次正常打开时执行前向迁移。
- 不接管没有版本标记但已有对象的 SQLite 文件；拒绝不兼容字段、主键、外键以及缺失/被削弱的审核保护触发器。
- 新审核摘要保留产品结构、原尺寸及标注、卖点真实性、平台与清晰度四项核验；未完成全部项目的“通过”状态会被拒绝。
- 旧审核记录缺少四项核验数据时保留历史，但迁移后撤销发布就绪状态，标记“历史审核需复核”。
- 健康检查使用 SQLite 只读连接，不创建、迁移或修复数据库。
- 校验任务表与 JSON 主记录的冗余字段、图片清单、模板名称/摘要、导入标记及审核事件。
- 文件名忽略大小写去重；有效 V1 备份只在临时快照中升级，原始源库保持不变。

## 表结构
| 表 | 用途 |
| --- | --- |
| jobs | 任务元数据、阶段、审核摘要、乐观版本 |
| job_files | 输出文件名与 SHA256 |
| review_events | 逐次审核历史，普通 SQL UPDATE/DELETE 被触发器拒绝 |
| templates | 布局 JSON 与摘要 |
| imported_files | 旧 JSON 来源路径、摘要与幂等导入标记 |

数据库不保存原始商品图片、API 密钥或客户图纸。SHA256 不是数字签名或不可篡改审计。

## 管理命令
    python scripts/db_admin.py init
    python scripts/db_admin.py check
    python scripts/db_admin.py import-legacy --dry-run
    python scripts/db_admin.py import-legacy
    python scripts/db_admin.py backup --output backups/huangren.sqlite3
    python -m unittest discover -s tests -v
    python -m compileall -q src scripts tests app.py

check 是只读扫描。V1 可只读检查并显示迁移警告；正常应用打开时会执行 V1→V2 迁移。迁移前先停止网页服务并备份 .local/；迁移不会删除旧 JSON。恢复前关闭所有使用数据库的程序；有 -wal/-shm 文件时拒绝覆盖。

## 限制
数据库仍是单机 SQLite，没有账号/角色权限、云端同步或防篡改数字签名。不要让多台电脑同时写同一个共享盘数据库。商品图、审核 ZIP 与数据库元数据需分别备份；迁移后在目标电脑核对数量并演练恢复。
