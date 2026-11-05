# Issue #2 最小修复批次

来源：https://github.com/hren44813-dotcom/huangren/issues/2 （含 5 条进展评论）。
核对日期：2026-11-05。

## 基线与交付约束

- `main` 为 `45cc20b`；PR #1 未合并，其功能分支为 `90e5373`，已涉及 91 个文件。
- 审计正文的未勾选框不是当前修复状态：`8966f54` 已修单位大小写、价格排序、显式详情跳转和未知分页；第二批已加入 capture_batch_id 与断点恢复。下面列出剩余验证/修复，不重复移植已完成代码。
- 本次分支 `fix/issue-2-p0-unit-boundaries` 基于 `90e5373`；每个修复另开小 PR，以现有功能分支为基线查看增量。不得推送该功能分支，不合并 PR #1，不把这 91 个文件包装成新的 main PR。
- 每批独立：先运行新增反例证明失败，再最小修复，再跑相关测试和全量离线测试；不改 schema，不修改生产 SQLite，不联网抓取真实供应商数据。
- 本次执行范围为第 1 批；其余为后续顺序。Windows 可见浏览器验收独立记录，离线测试不能替代真实采集验收。

## 批次顺序

下表源码路径均相对 `src/ecom_images/`，脚本、测试和工作流使用仓库相对路径。

| 批次 | 优先级 | 文件 | 回归用例 / 验收 |
|---|---|---|---|
| 1 单位和数值边界 | P0 | `image_evidence_gate_v13.py`；核对 `model_evidence_v13/normalize.py`；`tests/test_first_batch_data_accuracy.py`；`tests/test_model_evidence_reconciliation_v13.py` | `6 MN.m`≠`6 mN.m`、`N`≠`n`、`kg`≠`g`；`16`、`1E6`、`1E+6`、`1e+6`、`X6`、`6 N.mX` 不匹配 `6 N.m`；`N·m`/`N⋅m`/`N.m` 明确等价；真实已审核主张经过 build_job 拒绝错误文案且无输出文件。 |
| 2 实际详情页验证 | P1 | `supplier_capture_validation.py`；`supplier_capture/batch.py`；`scripts/supplier_catalog_capture.py`；`tests/test_supplier_capture_validation.py`；`tests/test_second_batch_capture_recovery.py` | 非空登录页、外域伪商品路径、非商品路径、缺失 detail_url、空白正文均不能计入有效详情或复用；合法详情通过。当前代码只在 detail_url 存在时验证，独立校验只检查正文文件大小。 |
| 3 时间验证和最新价格 | P1 | `supplier_db/helpers.py`、`writes.py`、`reports.py`；`tests/test_first_batch_data_accuracy.py`；`tests/test_supplier_catalog_db.py` | 先 10/29 ￥20 后 10/28 ￥10，七个 latest 字段来自同一最新观察；时区换算、Z/offset、小数秒、非法/缺失时间；同一时刻用稳定二级键；旧观察不能回写当前字段和 last_seen。现有排序已改 observed_at，但仍直接比较未经统一验证的文本。保留历史原件，不自动清洗现有库。 |
| 4 分页状态一致性 | P1 | `supplier_capture/audit.py`；`supplier_capture_validation.py`；`tests/test_first_batch_data_accuracy.py`；`tests/test_supplier_capture_validation.py` | 无总数、相互冲突的总数、缺页、空页、文件/记录页码不一致均不是 complete；明确一致且完整的页组通过；本地/独立审核一致。未知总数的原始漏洞已修，先补边界，只有复现缺口才改源码。 |
| 5 批次与时间新鲜度 | P1 | `supplier_capture/batch.py`、`export.py`；`supplier_capture_validation.py`；`supplier_db/helpers.py`；`tests/test_second_batch_capture_recovery.py`；新增 `tests/test_supplier_capture_freshness.py` | 跨批次页/旧 snapshot 排除；同批跨日续采、采集跨度超限、缺失/非法时间、未来时间；重建导出只更新导出时间，不能充当采集时间。保留 capture_batch_id，不再创造同义 run_id；新鲜度阈值作为显式策略参数，固定 now 测试，不擅定业务天数。旧新混用已有修复，新鲜度仍待实现。 |
| 6 失败恢复和翻页稳定性 | P1 | `scripts/supplier_catalog_capture.py`；`supplier_capture/batch.py`、`runner_helpers.py`；`tests/test_second_batch_capture_recovery.py` | 坏/空/错误批次详情重采；恢复后 capture_errors.json 落盘清除并重启验证；翻页空 fingerprint 不成功，只有非空且改变的指纹和正确页码才通过。已有实现先验证，不额外重构。 |
| 7 listing-only Actions | P1 | `.github/workflows/supplier-catalog-collection.yml`；新增 `tests/test_supplier_collection_modes.py`；必要时提取一个参数构建脚本 | 执行工作流中的校验命令（替换外部进程为记录 argv/退出码的边界）：collect_details=false 时独立验证和最终 DB 门禁均不带 require-details；true 时两处都带；任一失败仍导致最终失败。不只断言 YAML 包含某段文本。 |
| 8 多行审核说明 | P1/P2 | `knowledge_v13.py`；`knowledge_review_v13.py`；`knowledge_review_ui_v13.py`（仅必要时）；`tests/test_knowledge_review_v13.py`、`tests/test_knowledge_review_ui_v13.py` | 备注与冲突说明允许 LF/CRLF，统一换行并保留长度限制；拒绝孤立 CR、NUL、其他控制字符；身份/型号等单行字段保持严格。真实保存后读取审核记录验证。 |
| 9 旋转 PDF 预览 | P1/P2 | `knowledge_review_v13.py`；`tests/test_knowledge_review_v13.py` | 同一文字页 0/90/180/270° 调用 render_segment_preview，断言图像尺寸和高亮像素区域相对无高亮图改变；同时覆盖 bbox 与文本定位。 |

统一业务编排/面板放在以上门禁修复后单独设计，不与缺陷修复或数据库结构变更混合。

## 本次 Task 1：补齐 P0 边界

### Interfaces

- `_contains_value(field_text: str, value: str, unit: str) -> bool` 保持签名和现有明确等价单位写法。
- `_unit_key` / `_value_key` 的大小写保留实现已经存在，只添加 MN/mN、N/n、kg/g 区分与明确等价写法的验证。
- 只修改边界字符类；不引入通用 SI 解析器或隐式倍率转换。

### 执行步骤

1. 基线：`python -m unittest discover -s tests`。已运行：387 项通过。
2. 在 `tests/test_first_batch_data_accuracy.py` 补大小写/单位矩阵与大写相邻字符反例；在 `tests/test_model_evidence_reconciliation_v13.py` 用真实已审核主张及 build_job 验证 `X6 N.m`、`1E6 N.m`、`6 N.mX` 抛出值不一致且不落盘图片。
3. 运行：`python -m unittest discover -s tests -p 'test_first_batch_data_accuracy.py' -v` 与 `python -m unittest discover -s tests -p 'test_model_evidence_reconciliation_v13.py' -v`。预期新边界反例 FAIL，既有单位区分和正例 PASS；保存 RED 结果。
4. 修复 `image_evidence_gate_v13.py:_contains_value` 的左右边界，使保留大小写时也排除大写 ASCII 字母；左侧排除加号，防止取科学计数法指数的尾部数字。unit 归一化不变。
5. 同样两组测试应 PASS；然后 `python -m compileall -q src scripts tests app.py`、`python -m unittest discover -s tests` 全量通过；`git diff --check`。
6. 独立复核增量，提交测试和修复；推送新分支并创建小型草稿 PR（base 为已有功能分支），交付完整计划与 RED/GREEN 记录。

## Review Focus

- 保留大小写后不能沿用仅适用于 casefold 文本的 `[a-z]` 边界。
- 不将科学计数法的尾数当作独立值；不把较长单位/标识符中的子串当作证据。
- 中文邻接、无空格 `6N.m`、显式乘号归一化和不含单位的普通文本匹配仍可用。
- 图像生成前门禁的失败必须发生在输出图片写入之前。

## 执行记录

- 基线：387 tests / OK（8.211s）。
- 确认复现：`_contains_value('X6 N.m', '6', 'N.m')` 和 `...('6 N.mX', ...)` 均错误返回 True。
- 用户已明确授权列出计划后执行第 1 批，无需再次请求启动确认。
- RED：`test_first_batch_data_accuracy.py` 9 项中 4 个边界 subtest 失败；`test_model_evidence_reconciliation_v13.py` 13 项中 3 个真实制图 subtest 因未抛异常而失败（修复前）。
- GREEN：同两组分别 9/9 和 13/13 通过；`compileall` 通过；全量离线测试 391/391 通过（7.426s）；`git diff --check` 通过。
- 独立复核认可大写边界修复，并发现既有 `1E+6` / `1e+6` 同源漏洞：补 2 个匹配反例和 1 个真实制图反例，均确认 RED；左边界加入加号后 GREEN。未引入倍率换算，显式带正号的值也采用保守匹配。
- 最终：相关 22 项通过，全量离线 391/391 通过（8.207s）；`compileall` 和 `git diff --check` 通过。
- `normalize.py` 无需重复修改。远端按「回归测试 → 最小修复」两次提交；使用已连接 GitHub 应用发布，因为本地 git push 没有认证。PR 仅展示 4 文件增量。
- 复核范围限本批增量及相关测试；后续批次、真实供应商采集、Windows 浏览器和通用单位解析仍需各批独立验收。
