# V12 商品档案部署验收表

- [ ] 已关闭写库的网页或脚本，已备份整个 `.local/` 目录（包括 V10 SQLite + 老 JSON）
- [ ] `python scripts/db_admin.py check` 通过（原任务审核表）
- [ ] `python scripts/catalog_admin.py init` 成功（只增建新表）
- [ ] `python scripts/catalog_admin.py check` 输出 `summary.ok=true` 和 `audit.ok=true`
- [ ] 下载 CSV 空白模板，仅填写已有来源的商品参数
- [ ] 对每家店各挑一个商品、多规格 SKU 进行 `import-csv` 预演
- [ ] 冲突样本（SKU 编码重复但参数不同）被阻止且数据不被覆盖
- [ ] `import-csv --apply` 后，按店铺筛选 SKU 数量和原 Excel 一致
- [ ] 原 V10 制图任务、模板、审核事件仍可读取
- [ ] 手动关联一个已核实 SKU 与制图任务，重复关联不会生成重复记录
- [ ] 实际进行一次 `db_admin.py backup`，用测试位置恢复并比较两种 `check`
- [ ] 在真实运营电脑用浏览器验证 CSV 上传、预演、应用、列表页面操作
- [ ] 审核原图、尺寸图仍有单独安全备份，并未上传公共 GitHub

注意：CI 仅用模拟记录验证代码及 SQLite 行为；完整生产验收以你自己的真实数据库迁移结果为准。
