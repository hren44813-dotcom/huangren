# V13 Evidence Review Workflow — Execution Ledger

Base commit: 62e549ab4df05a3c0937d6bbf14eec92f68cea9d
Branch: feat-v13-evidence-review-workflow

Ruling: Use a GitHub feature branch rather than writing directly to main — protects the shared default branch and allows CI/PR inspection.

Ruling: Reuse the V13 append-only schema and triggers instead of creating V17/V18 tables — existing claim/evidence/review/conflict events already provide the required persistence and acceptance gates.

Ruling: Make claim+evidence creation and review+optional state transition atomic — a partial operation would leave a misleading half-reviewed record.

Ruling: PDF preview re-hashes stored bytes before rendering — visual evidence must correspond to the source fingerprint registered in the database.
