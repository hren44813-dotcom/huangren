# Supplier catalog database and collection process

## Scope and storage

The supplier catalog database is a separate local SQLite database at .local/supplier_catalog.sqlite3. It is not the V13 evidence ledger and does not overwrite the image-workflow database. The schema, importer, audit logic, tests and GitHub Actions workflow are committed; the live database is generated from captured pages and uploaded as a workflow artifact rather than committing a changing binary database to the repository.

The first-page snapshot in this repository contains 16 visible items and shows pagination 1/139. That is a starting checkpoint, not a claim that all 139 pages or all product details have been collected.

## Normalized tables

| Table | Purpose |
|---|---|
| supplier_catalog_suppliers | Supplier identity and storefront URL |
| supplier_catalog_products | Stable product identity keyed by canonical product URL, current title/model hints and first/last seen |
| supplier_catalog_runs | Collection run identity and input manifest hash |
| supplier_catalog_run_events | Append-only started/complete/partial/failed events |
| supplier_catalog_pages | Per-page checkpoint, page number, pagination marker, content hash and raw JSON |
| supplier_catalog_observations | Append-only listing snapshots for title, price/currency, MOQ, displayed sales, delivery and source |
| supplier_catalog_model_mentions | Model strings mentioned in seller titles or source fields; explicitly unverified |
| supplier_catalog_detail_observations | Timestamped detail-page capture, structured fields and source/body hashes |
| supplier_catalog_attributes | Specification key/value pairs with table/definition/JSON-LD locator |
| supplier_catalog_options | Visible SKU/option groups, selected/disabled state |
| supplier_catalog_errors | Invalid checkpoints, missing files and per-product capture failures |
| supplier_catalog_meta | Schema version and initialization metadata |

Observation, page, option, attribute, error and run-event tables are append-only. Re-importing an identical capture is idempotent; a changed price or later capture creates a new observation instead of rewriting history. The current product row is a convenience index and can be refreshed from newer observations.

## Commands

Seed a local resume checkpoint from the committed first-page snapshot:

```powershell
python scripts/seed_supplier_capture.py
```

For a full visible-browser run on Windows, run the PowerShell orchestrator below. It preserves checkpoints, allows manual login/CAPTCHA handling in the visible browser, retries ordinary page errors, syncs the database, exports CSVs and returns a non-zero exit code if completeness checks fail. On the first run, the switch installs dependencies and then immediately starts collection. If dependencies are already installed, omit it. If a run is interrupted, rerun without the switch to resume from saved checkpoints:

```powershell
.\scripts\run_full_supplier_capture.ps1 -InstallDependencies
```

Alternatively, run the lower-level commands below for manual control; refresh existing checkpoints when the goal is to capture new price observations:

```powershell
python scripts/supplier_catalog_capture.py listing --max-pages 139 --delay 2.5 --refresh-existing
python scripts/supplier_catalog_capture.py details --delay 3
python scripts/supplier_catalog_capture.py audit
```

The capture script supports --headless --no-prompt for automation. If the site returns a CAPTCHA, login wall or access restriction, non-interactive mode stops and keeps the checkpoints; it does not attempt to bypass the check.

Sync captures into the normalized database and export CSVs:

```powershell
python scripts/sync_supplier_catalog_db.py sync
python scripts/sync_supplier_catalog_db.py audit
python scripts/sync_supplier_catalog_db.py search CL226
python scripts/sync_supplier_catalog_db.py export
```

For a preview without database writes:

```powershell
python scripts/sync_supplier_catalog_db.py sync --dry-run
```

## GitHub Actions

The Supplier catalog collection workflow supports manual workflow_dispatch after the workflow is present on the default branch. It also runs on relevant code pushes to the feature branch while this PR is being developed. The full default run requests up to 139 listing pages and then visits each captured product detail page; it may take hours and can stop early if the marketplace requires interactive verification.

The workflow uploads the SQLite database, JSON checkpoints, text detail captures, CSV exports and audit reports as a 30-day artifact. It does not commit the generated database or supplier records to Git. If the run is incomplete, the artifact is still uploaded, but the final quality gate fails so a partial crawl cannot be mistaken for a successful full collection. The first automated attempt on 2026-10-28 was blocked by an Alibaba login/CAPTCHA/access restriction and captured only the existing 16-item first-page checkpoint; see collection_run_2026-10-28.md.

## Data-quality and evidence rules

- A complete listing audit requires every page number visible in pagination, no corrupt checkpoint, no page-number mismatch and no empty visible product page.
- A complete detail audit requires one valid detail record and non-empty text for every product, no orphan details, no corrupt JSON and no unresolved capture errors.
- Unshown sales counts remain NULL, not zero. Missing prices/MOQ remain missing rather than being guessed.
- Prices, MOQ, sales, delivery estimates and product-title specifications are timestamped seller-page observations. They are not verified manufacturer facts.
- V13 document import stores detail Markdown as supplier_document / unverified. It does not create accepted parameter claims or automatically bind a store SKU to a manufacturer model.
- Browser profiles, cookies, API credentials and local databases must not be committed. The database is not a tamper-proof audit log; its append-only triggers are an application-level guardrail.

## 第二批：刷新采集与断点续采（批次隔离）

- **新的一次价格观察**：`python scripts/supplier_catalog_capture.py listing --refresh-existing --max-pages 139` 会建立新的 `listing_batch.json`，每页检查点标记 `capture_batch_id`。旧批次的页面不会被计入当次 `catalog.json` 或完整性审核；旧 SQLite 观察记录仍可用于历史价格分析。
- **接着上一次未完成的采集**：运行 `listing --max-pages 139`（不加 `--refresh-existing`）。仅跳过同批次、非空、分页一致且链接有效的检查点；失败页会尝试重采。
- **Windows 一键脚本**：首次执行将启动新的批次；中断后原命令会继续同一批次。需要重新开始新一天的观察时，加 `-NewBatch`。此前保存的历史页面不会被误认为本次新增的有效数据。
- **详情采集**：同批次已保存的有效商品正文会跳过；空正文、无效商品地址或旧批次详情会重新采集。成功重试或跳过时清理已解决的 `capture_errors.json` 失败项。
- **验收状态**：`scripts/verify_supplier_pipeline.py` 的独立原始文件校验是最终完成判定；商品列表和详情分别有 `listing_status` / `detail_status`。列表-only 没有请求详情时可报告 complete，但不代表详情已采集。
- **注意**：系统不绕过登录/验证码；首次刷新若访问受限，将保留 partial 及已有文件。不可把 SQLite 完整性、历史页面数量或未修改的第一页面快照当成当天采集完成。
