# Supplier automation production gate

## Two distinct automation modes

1. **Offline CI (automatic on pull requests):** recreate the committed first-page snapshot, import it into a clean SQLite database, check schema integrity and validate coverage directly from source checkpoint files. The expected result is PARTIAL (1/139 pages). CI fails if the system incorrectly reports complete. This mode requires no marketplace credentials and is suitable for repeatable testing.
2. **Live full collection (manual workflow_dispatch or local visible browser):** navigate pages and product details with respectful delays, store checkpoints, normalize observations and export an audit bundle. Live website interaction is not automatically triggered for every code push because the supplier currently requires login/CAPTCHA from GitHub-hosted Chromium.

## Full-catalog acceptance criteria

- All page numbers 1 through the live site's last reported page are captured, nonempty, readable and agree with their pagination marker.
- The deduplicated product URLs in catalog.json exactly match the union of checkpoint page URLs.
- Every product has one valid detail JSON with matching item ID and source URL, plus a nonempty text file.
- No unresolved detail capture errors remain.
- The SQLite PRAGMA integrity check and foreign-key check pass.
- The normalized database has one or more observations per catalog product.
- Both the independent capture validator and normalized DB quality gate return complete.
- Supplier-page attribute claims remain unverified in V13 until independently reviewed.

## Commands

Offline smoke test (no network):

```powershell
python scripts/seed_supplier_capture.py
python scripts/sync_supplier_catalog_db.py sync --require-details
python scripts/verify_supplier_pipeline.py --require-details --expect-status partial
python scripts/sync_supplier_catalog_db.py audit
```

Locally collected full catalog:

```powershell
.\scripts\run_full_supplier_capture.ps1 -InstallDependencies
python scripts/verify_supplier_pipeline.py --require-details --expect-status complete
python scripts/sync_supplier_catalog_db.py audit --require-complete --require-details
```

If the source website requires a login or CAPTCHA, complete it using the site's normal interface in a visible browser. Do not use automation to defeat access controls. Retain a partial capture with honest failure reasons if login cannot be completed.

## Known limitation

A 2026-10-28 GitHub-hosted headless attempt was blocked by the marketplace: it saved only the seed first-page snapshot (16 products) and no detail pages. A healthy database and passing unit tests are not evidence that all pages were successfully scraped. The updated independent checker protects this boundary.
