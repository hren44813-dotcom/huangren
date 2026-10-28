# V13 Evidence Review Workflow — Execution Ledger

Base commit: 62e549ab4df05a3c0937d6bbf14eec92f68cea9d
Branch: feat-v13-evidence-review-workflow

Ruling: Use a GitHub feature branch rather than writing directly to main — protects the shared default branch and allows CI/PR inspection.

Ruling: Reuse the V13 append-only schema and triggers instead of creating V17/V18 tables — existing claim/evidence/review/conflict events already provide the required persistence and acceptance gates.

Ruling: Make claim+evidence creation and review+optional state transition atomic — a partial operation would leave a misleading half-reviewed record.

Ruling: PDF preview re-hashes stored bytes before rendering — visual evidence must correspond to the source fingerprint registered in the database.


Ruling: Expose local document upload in the existing Streamlit tab — this completes the import-to-review path without adding a second UI framework; uploaded files are staged beneath the verified database directory and the temporary copy is deleted after import.

Ruling: Keep physical-photo source classification out of the document uploader — this uploader accepts document formats only, and must not imply image/OCR support.

Ruling: Return SKU free-text model separately from manufacturer model identity in the review queue — identical strings do not prove an approved SKU-to-model mapping.

Verification checkpoint: GitHub Actions run 40622739692 passed the full 278-test suite on Python 3.10 and Python 3.12.
