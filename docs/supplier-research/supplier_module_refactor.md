# Supplier module refactor: compatible V1/V13 upgrade

## Scope (stage 2)

The legacy supplier catalog code was split into smaller units, without replacing
the existing databases, table names, trigger rules, SQL schema version or file
layout. The V13 evidence system is a separate database and remains unchanged.

The original import paths remain available:

- `ecom_images.supplier_catalog_db`
- `ecom_images.supplier_catalog_capture`
- `scripts/supplier_catalog_capture.py`

All call sites in existing scripts, tests and Streamlit integrations can keep
using these modules. The old Python modules are now thin forwarding facades.

## File ownership

| New module | Responsibility |
| --- | --- |
| `supplier_db/schema.py` | Supplier SQLite V1 schema, initialization, connection |
| `supplier_db/helpers.py` | Input normalization, snapshots and manifest hashes |
| `supplier_db/writes.py` | Product/observation/detail/option/event inserts |
| `supplier_db/service.py` | Transactional capture-to-DB synchronization |
| `supplier_db/reports.py` | Integrity audit, search, CSV exports |
| `supplier_capture/browser_js.py` | DOM extraction snippets |
| `supplier_capture/listing.py` | Listing parsing and checkpoint observation |
| `supplier_capture/detail.py` | JSON-LD, SKU options, Markdown provenance |
| `supplier_capture/audit.py` | Source checkpoint and detail audit reports |
| `supplier_capture/export.py` | Deduplicated catalog CSV and JSON exports |
| `supplier_capture/runner_helpers.py` | CLI arguments, browser and human checks |

**All the above Python files and both legacy facades are at most 300 lines.**
The rest of the repository is out of scope for this particular file-size gate.

## Migration safety contract

- **No SQLite migration is necessary.** The supplier schema stays at
  `PRAGMA user_version=1`, with the same supplier tables, indexes and
  append-only triggers.
- Existing `.local/supplier_catalog.sqlite3` databases may be reopened,
  and running `initialize_supplier_db` repeatedly does not replace rows.
- Unknown database versions are rejected instead of being automatically
  converted or overwritten.
- Defaults for database and first-page snapshot files remain rooted at the
  repository directory after moving source files into packages.
- The V9/V12/V13 database is not altered by supplier catalog initializers;
  accepted knowledge claims still require independent evidence review.
- Existing data captures, source documents and cookies should never be
  committed to a public GitHub repository.

For safety, take a backup of both SQLite databases before making any future
schema changes. This refactor itself performs no schema migration.

## Commands and verification

```powershell
git fetch origin
git switch feat-v13-evidence-review-workflow
git pull --ff-only
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
python scripts/system_healthcheck.py
python scripts/seed_supplier_capture.py
python scripts/sync_supplier_catalog_db.py sync --require-details
python scripts/verify_supplier_pipeline.py --require-details --expect-status partial
```

The last check is **expected to report partial** for the stored page-1
supplier snapshot. This does not mean the code or database integrity failed;
it means the actual 139-page/individual-detail collection is incomplete.
A complete external collection must pass separate full-coverage checks.

## Regression coverage

`tests/test_supplier_module_refactor.py` verifies:

1. Old import names map to the same new implementations.
2. V1 SQL table/trigger definitions and user_version remain identical on reopen.
3. Pre-existing supplier rows survive repeated initialization.
4. Unknown versions reject migration and preserve original data.
5. V13 document/evidence tables remain isolated from supplier database writes.
6. All new supplier source files, compatibility facades and capture script
   stay within the 300-line maintainability limit.

Existing unit, CLI, E2E image-generation, offline supplier smoke and Windows
PowerShell syntax checks continue to run in GitHub Actions. Successful
CI proves code-level compatibility; it does not prove that remote supplier
pages can be accessed without an interactive CAPTCHA.
