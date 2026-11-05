# V13 Evidence Review Workflow Implementation Plan

> For agentic workers: REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Integrate a Chinese visual evidence-review workflow into the existing Streamlit app while preserving V13 append-only data and acceptance gates.

**Architecture:** Add a service module for review queue queries, source-integrity-checked PDF previews, atomic candidate claim/evidence creation, atomic review/state transitions, and open-conflict listing. Add one Streamlit tab with local file upload that calls the service and existing V13 APIs; no schema migration.

**Tech Stack:** Python 3.10/3.12, SQLite V13, PyMuPDF, Streamlit, unittest, GitHub Actions.

**Spec:** docs/superpowers/specs/2026-10-28-v13-evidence-review-design.md

## Global Constraints

- Keep V13 schema version 1 and all V10/V12/V13 historical rows unchanged.
- Do not create accepted claims automatically; database evidence and independent-review gates remain authoritative.
- Verify source SHA-256 before creating evidence from indexed text or rendering a PDF preview.
- Keep PDF physical page, PDF bbox, DOCX paragraph/table, Markdown/TXT line, and Excel cell locations distinct.
- Do not infer or confirm SKU-to-manufacturer-model mappings.
- Use append-only events and atomic transactions for multi-record operations.

## Review Focus

- Missing or tampered source bytes must block evidence creation and preview.
- Unknown manufacturer model IDs and segment IDs must fail without partial rows.
- Acceptance with an author-only review or contradictory evidence must roll back the review and state event together.
- Non-PDF locations must remain visible without invented PDF page numbers.
- Conflict resolution must require an existing source and written rationale.

---

### Task 1: Transactional V13 review service

**Files:**
- Create: src/ecom_images/knowledge_review_v13.py
- Test: tests/test_knowledge_review_v13.py

**Interfaces:**
- Produces list_review_claims(path, model_code="", attribute="", state="", limit=100), list_open_conflicts(path, model_code="", attribute="", limit=100), list_review_sources(path, limit=200), get_claim_review_detail(path, claim_id), create_claim_from_segment(path, segment_id, model_id, attribute, literal_value, unit, claim_kind, created_by, evidence_role="supports"), render_segment_preview(path, segment_id, scale=1.25), and record_claim_review(path, claim_id, verdict, reviewer_role, reviewer_name, method, notes, decision_state="", actor="", decision_note="").
- Uses existing V13 tables and triggers; no schema changes.

- [x] Step 1: Write tests for atomic candidate creation, exact location metadata, source-hash mismatch rollback, PNG PDF preview with highlighted bbox, review acceptance gates/rollback, contradiction reopening, and open-conflict filtering.
- [x] Step 2: Run the new test module and confirm expected failures because the service API is not yet implemented.
- [x] Step 3: Implement the minimal service API in src/ecom_images/knowledge_review_v13.py. Multi-row claim/evidence and review/state operations must each use one transaction.
- [x] Step 4: Re-run the new test module and then the existing V13 claim/ingestion tests.
- [x] Step 5: Commit the service and tests.

### Task 2: Streamlit evidence-review tab

**Files:**
- Create: src/ecom_images/knowledge_review_ui_v13.py
- Modify: app.py
- Test: tests/test_knowledge_review_ui_v13.py

**Interfaces:**
- Expose render(st) from the UI module and add a tab named ⑦ 参数证据审核 in app.py.
- Show a local file uploader with a document extension allowlist and 100 MiB limit, model/attribute search, registered model identities, source segments and source locators, PDF page preview, candidate claim form, claim review form, and unresolved conflicts.
- Keep source identity and location visible; all write actions require explicit form submission.

- [x] Step 1: Add regression tests proving the app imports and mounts the review renderer and exposes the local file upload path.
- [x] Step 2: Run the test and confirm it fails before UI wiring exists.
- [x] Step 3: Implement the UI module and mount its tab in app.py without importing Streamlit in the service layer.
- [x] Step 4: Run UI wiring and all service tests.

### Task 3: Operator documentation and CI acceptance

**Files:**
- Create: docs/knowledge-evidence-review-v13.md
- Modify: README.md
- Test: full repository unittest suite via existing .github/workflows/ci.yml

- [x] Step 1: Document launch, initialization, candidate creation, acceptance gates, conflict resolution, source-integrity failures, and limitations.
- [x] Step 2: Run the full unit-test suite on GitHub Actions for Python 3.10 and 3.12.
- [x] Step 3: Inspect the workflow logs and branch diff; fix any Critical/Important issue with a regression test.
- [x] Step 4: Open a pull request to main and report the exact CI outcome and remaining limits.


## Verification record

- Latest implementation commit before this plan/ledger refresh: 65819d7ffcbb594dc61e431f5f946e091c088392.
- GitHub Actions run 40622739692 passed on Python 3.10 and 3.12, with 278 tests passing in each matrix job.
- The final documentation/plan commit is also checked by the pull request workflow; see the final response for the branch-head run.
