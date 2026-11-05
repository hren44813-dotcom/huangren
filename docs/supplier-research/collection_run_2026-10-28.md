# DGDeler full catalog collection attempt — 2026-10-28

## Result

**Status: partial. This run did not collect the full catalog.**

- GitHub Actions run: https://github.com/hren44813-dotcom/huangren/actions/runs/40631420848
- Artifact: supplier-catalog-2 (artifact ID 12790829038; expires 2026-11-27)
- Pagination visible in the saved source: 1/139
- Listing pages captured: 1 of 139
- Unique product records: 16
- Listing observations stored in SQLite: 16
- Product detail observations: 0
- Detail records missing: 16
- Capture errors: 1

## Database integrity

The generated SQLite database passed SQLite integrity and foreign-key checks. The database contains 16 product rows, 16 listing observations, one page checkpoint, zero detail observations and one capture error. Database integrity is healthy; collection coverage is not complete.

The listing audit reports partial, with 138 page numbers missing. The detail audit reports partial, with zero valid detail records and 16 missing records.

## Blocking condition

GitHub-hosted headless Chromium was redirected to an Alibaba login/CAPTCHA/access-restriction page during the first listing navigation. The detail attempt encountered the same restriction. Non-interactive mode stopped as designed; it did not attempt to bypass the check. The workflow still uploaded the partial database, source checkpoint, CSV exports and audit reports, and its final completeness gate failed.

## Next action

Run scripts/run_full_supplier_capture.ps1 on the operator's Windows machine. The script opens a visible Chromium profile so the operator can complete normal login/site verification, then collects listing pages and details, syncs SQLite, exports CSVs and checks completeness. Resume from saved checkpoints after interruptions. Do not mark the catalog complete until the audits show all visible listing pages and all product details captured.
