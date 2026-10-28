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

`powershell
python scripts/seed_supplier_capture.py
`

For a full visible-browser run, log in or complete site verification yourself if requested. Refresh existing checkpoints when the goal is to capture new price observations:

`powershell
python scripts/supplier_catalog_capture.py listing --max-pages 139 --delay 2.5 --refresh-existing
python scripts/supplier_catalog_capture.py details --delay 3
python scripts/supplier_catalog_capture.py audit
`

The capture script supports --headless --no-prompt for automation. If the site returns a CAPTCHA, login wall or access restriction, non-interactive mode stops and keeps the checkpoints; it does not attempt to bypass the check.

Sync captures into the normalized database and export CSVs:

`powershell
python scripts/sync_supplier_catalog_db.py sync
python scripts/sync_supplier_catalog_db.py audit
python scripts/sync_supplier_catalog_db.py search CL226
python scripts/sync_supplier_catalog_db.py export
`

For a preview without database writes:

`powershell
python scripts/sync_supplier_catalog_db.py sync --dry-run
`

## GitHub Actions

The Supplier catalog collection workflow supports manual workflow_dispatch after the workflow is present on the default branch. It also runs on relevant code pushes to the feature branch while this PR is being developed. The full default run requests up to 139 listing pages and then visits each captured product detail page; it may take hours and can stop early if the marketplace requires interactive verification.

The workflow uploads the SQLite database, JSON checkpoints, text detail captures, CSV exports and audit reports as a 30-day artifact. It does not commit the generated database or supplier records to Git. If the run is incomplete, the artifact is still uploaded, but the final quality gate fails so a partial crawl cannot be mistaken for a successful full collection.

## Data-quality and evidence rules

- A complete listing audit requires every page number visible in pagination, no corrupt checkpoint, no page-number mismatch and no empty visible product page.
- A complete detail audit requires one valid detail record and non-empty text for every product, no orphan details, no corrupt JSON and no unresolved capture errors.
- Unshown sales counts remain NULL, not zero. Missing prices/MOQ remain missing rather than being guessed.
- Prices, MOQ, sales, delivery estimates and product-title specifications are timestamped seller-page observations. They are not verified manufacturer facts.
- V13 document import stores detail Markdown as supplier_document / unverified. It does not create accepted parameter claims or automatically bind a store SKU to a manufacturer model.
- Browser profiles, cookies, API credentials and local databases must not be committed. The database is not a tamper-proof audit log; its append-only triggers are an application-level guardrail.
