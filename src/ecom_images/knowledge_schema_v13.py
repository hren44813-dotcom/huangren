"""Append-only V13 knowledge schema; preserves existing V10/V12 tables."""
from __future__ import annotations
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator
from .catalog_v12 import _validate_catalog
from .database_v9 import DEFAULT_DB, open_database

KNOWLEDGE_SCHEMA_VERSION=1
_TABLES={"knowledge_meta","catalog_models","catalog_sku_model_links","catalog_sku_model_events","knowledge_sources",
"knowledge_claims","knowledge_claim_evidence","knowledge_claim_reviews","knowledge_claim_events","knowledge_conflicts","knowledge_conflict_events"}
_DDL=(
"""CREATE TABLE knowledge_meta(key TEXT PRIMARY KEY,value TEXT NOT NULL)""",
"""CREATE TABLE catalog_models(id TEXT PRIMARY KEY,manufacturer_name TEXT NOT NULL,model_code TEXT NOT NULL COLLATE NOCASE,
category TEXT NOT NULL,series TEXT NOT NULL DEFAULT '',created_utc TEXT NOT NULL,
UNIQUE(manufacturer_name COLLATE NOCASE,model_code COLLATE NOCASE))""",
"""CREATE TABLE catalog_sku_model_links(id TEXT PRIMARY KEY,sku_id TEXT NOT NULL REFERENCES catalog_skus(id) ON DELETE RESTRICT,
model_id TEXT NOT NULL REFERENCES catalog_models(id) ON DELETE RESTRICT,created_by TEXT NOT NULL,note TEXT NOT NULL DEFAULT '',
created_utc TEXT NOT NULL,UNIQUE(sku_id,model_id))""",
"""CREATE TABLE catalog_sku_model_events(event_id INTEGER PRIMARY KEY AUTOINCREMENT,
link_id TEXT NOT NULL REFERENCES catalog_sku_model_links(id) ON DELETE RESTRICT,
state TEXT NOT NULL CHECK(state IN ('proposed','confirmed','rejected','withdrawn')),actor TEXT NOT NULL,note TEXT NOT NULL DEFAULT '',
source_id TEXT REFERENCES knowledge_sources(id) ON DELETE RESTRICT,created_utc TEXT NOT NULL,
CHECK(state<>'confirmed' OR (source_id IS NOT NULL AND length(trim(note))>0)))""",
"""CREATE TABLE knowledge_sources(id TEXT PRIMARY KEY,document_family TEXT NOT NULL DEFAULT '',original_filename TEXT NOT NULL,
source_kind TEXT NOT NULL CHECK(source_kind IN ('manufacturer_document','supplier_document','purchase_record','physical_photo',
'lab_report','platform_export','internal_note','other')),
authority_level TEXT NOT NULL CHECK(authority_level IN ('unverified','user_supplied','manufacturer_controlled','independent_test','system_export')),
sha256 TEXT NOT NULL UNIQUE CHECK(length(sha256)=64 AND sha256 NOT GLOB '*[^0-9a-f]*'),
size_bytes INTEGER NOT NULL CHECK(size_bytes>0),media_type TEXT NOT NULL DEFAULT '',
page_count INTEGER CHECK(page_count IS NULL OR page_count>0),document_number TEXT NOT NULL DEFAULT '',
revision_label TEXT NOT NULL DEFAULT '',issue_date TEXT NOT NULL DEFAULT '',storage_ref TEXT NOT NULL DEFAULT '',
metadata_json TEXT NOT NULL DEFAULT '{}',supersedes_source_id TEXT REFERENCES knowledge_sources(id) ON DELETE RESTRICT,
created_utc TEXT NOT NULL)""",
"""CREATE TABLE knowledge_claims(id TEXT PRIMARY KEY,subject_type TEXT NOT NULL CHECK(subject_type IN ('model','product','sku','asset')),
subject_id TEXT NOT NULL,attribute TEXT NOT NULL,literal_value TEXT NOT NULL,normalized_value_json TEXT NOT NULL DEFAULT 'null',
unit TEXT NOT NULL DEFAULT '',claim_kind TEXT NOT NULL CHECK(claim_kind IN ('catalog_transcription','supplier_assertion',
'physical_measurement','independent_test','manual_observation','system_inference')),created_by TEXT NOT NULL,
supersedes_claim_id TEXT REFERENCES knowledge_claims(id) ON DELETE RESTRICT,created_utc TEXT NOT NULL)""",
"""CREATE TABLE knowledge_claim_evidence(id TEXT PRIMARY KEY,claim_id TEXT NOT NULL REFERENCES knowledge_claims(id) ON DELETE RESTRICT,
source_id TEXT NOT NULL REFERENCES knowledge_sources(id) ON DELETE RESTRICT,
evidence_role TEXT NOT NULL CHECK(evidence_role IN ('supports','contradicts','context')),
pdf_page INTEGER CHECK(pdf_page IS NULL OR pdf_page>0),printed_page TEXT NOT NULL DEFAULT '',region_json TEXT NOT NULL DEFAULT '{}',
literal_excerpt TEXT NOT NULL DEFAULT '',extraction_method TEXT NOT NULL CHECK(extraction_method IN
('manual','pdf_text','ocr','measurement','manufacturer_confirmation','system_export','other')),
confidence_note TEXT NOT NULL DEFAULT '',created_by TEXT NOT NULL,created_utc TEXT NOT NULL)""",
"""CREATE TABLE knowledge_claim_reviews(id TEXT PRIMARY KEY,claim_id TEXT NOT NULL REFERENCES knowledge_claims(id) ON DELETE RESTRICT,
verdict TEXT NOT NULL CHECK(verdict IN ('supports','contradicts','inconclusive')),
reviewer_role TEXT NOT NULL CHECK(reviewer_role IN ('author','second_reviewer','manufacturer','independent_lab','warehouse','other')),
reviewer_name TEXT NOT NULL,method TEXT NOT NULL,notes TEXT NOT NULL,created_utc TEXT NOT NULL)""",
"""CREATE TABLE knowledge_claim_events(event_id INTEGER PRIMARY KEY AUTOINCREMENT,
claim_id TEXT NOT NULL REFERENCES knowledge_claims(id) ON DELETE RESTRICT,
state TEXT NOT NULL CHECK(state IN ('proposed','accepted','rejected','superseded','reopened')),
actor TEXT NOT NULL,note TEXT NOT NULL DEFAULT '',created_utc TEXT NOT NULL)""",
"""CREATE TABLE knowledge_conflicts(id TEXT PRIMARY KEY,claim_a_id TEXT NOT NULL REFERENCES knowledge_claims(id) ON DELETE RESTRICT,
claim_b_id TEXT NOT NULL REFERENCES knowledge_claims(id) ON DELETE RESTRICT,created_by TEXT NOT NULL,description TEXT NOT NULL,
created_utc TEXT NOT NULL,CHECK(claim_a_id<>claim_b_id),UNIQUE(claim_a_id,claim_b_id))""",
"""CREATE TABLE knowledge_conflict_events(event_id INTEGER PRIMARY KEY AUTOINCREMENT,
conflict_id TEXT NOT NULL REFERENCES knowledge_conflicts(id) ON DELETE RESTRICT,
state TEXT NOT NULL CHECK(state IN ('open','resolved','reopened')),actor TEXT NOT NULL,resolution_note TEXT NOT NULL DEFAULT '',
source_id TEXT REFERENCES knowledge_sources(id) ON DELETE RESTRICT,created_utc TEXT NOT NULL,
CHECK(state<>'resolved' OR (source_id IS NOT NULL AND length(trim(resolution_note))>0)))""",
"CREATE INDEX idx_models_code ON catalog_models(model_code)",
"CREATE INDEX idx_model_links_sku ON catalog_sku_model_links(sku_id)",
"CREATE INDEX idx_sources_family ON knowledge_sources(document_family,created_utc)",
"CREATE INDEX idx_claim_subject ON knowledge_claims(subject_type,subject_id,attribute)",
"CREATE INDEX idx_claim_evidence_claim ON knowledge_claim_evidence(claim_id,source_id)",
"CREATE INDEX idx_claim_review_claim ON knowledge_claim_reviews(claim_id,created_utc)",
"CREATE INDEX idx_claim_events_latest ON knowledge_claim_events(claim_id,event_id DESC)",
"CREATE INDEX idx_conflict_events_latest ON knowledge_conflict_events(conflict_id,event_id DESC)",
"""CREATE TRIGGER knowledge_claim_subject_exists BEFORE INSERT ON knowledge_claims
WHEN (NEW.subject_type='model' AND NOT EXISTS(SELECT 1 FROM catalog_models WHERE id=NEW.subject_id))
OR (NEW.subject_type='product' AND NOT EXISTS(SELECT 1 FROM catalog_products WHERE id=NEW.subject_id))
OR (NEW.subject_type='sku' AND NOT EXISTS(SELECT 1 FROM catalog_skus WHERE id=NEW.subject_id))
OR (NEW.subject_type='asset' AND NOT EXISTS(SELECT 1 FROM catalog_assets WHERE id=NEW.subject_id))
BEGIN SELECT RAISE(ABORT,'knowledge claim subject does not exist'); END""",
"""CREATE TRIGGER knowledge_claim_supersedes_same_subject BEFORE INSERT ON knowledge_claims
WHEN NEW.supersedes_claim_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM knowledge_claims old WHERE old.id=NEW.supersedes_claim_id
AND old.subject_type=NEW.subject_type AND old.subject_id=NEW.subject_id AND old.attribute=NEW.attribute)
BEGIN SELECT RAISE(ABORT,'replacement claim must target the same subject and attribute'); END""",
"""CREATE TRIGGER knowledge_conflict_same_attribute BEFORE INSERT ON knowledge_conflicts
WHEN NOT EXISTS(SELECT 1 FROM knowledge_claims a JOIN knowledge_claims b ON a.id=NEW.claim_a_id AND b.id=NEW.claim_b_id
WHERE a.subject_type=b.subject_type AND a.subject_id=b.subject_id AND a.attribute=b.attribute)
BEGIN SELECT RAISE(ABORT,'conflict claims must have the same subject and attribute'); END""",
"""CREATE TRIGGER knowledge_claim_acceptance_gate BEFORE INSERT ON knowledge_claim_events WHEN NEW.state='accepted' BEGIN
SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM knowledge_claim_evidence e WHERE e.claim_id=NEW.claim_id AND e.evidence_role='supports')
THEN RAISE(ABORT,'accepted claim requires supporting source evidence') END;
SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM knowledge_claim_reviews r WHERE r.claim_id=NEW.claim_id AND r.verdict='supports'
AND r.reviewer_role IN ('second_reviewer','manufacturer','independent_lab'))
THEN RAISE(ABORT,'accepted claim requires independent supporting review') END;
SELECT CASE WHEN EXISTS(SELECT 1 FROM knowledge_claim_reviews r WHERE r.claim_id=NEW.claim_id AND r.verdict='contradicts')
THEN RAISE(ABORT,'claim with a contradicting review cannot be accepted') END;
SELECT CASE WHEN EXISTS(SELECT 1 FROM knowledge_claim_evidence e WHERE e.claim_id=NEW.claim_id AND e.evidence_role='contradicts')
THEN RAISE(ABORT,'claim with contradicting evidence cannot be accepted') END;
END""",
"""CREATE TRIGGER knowledge_claim_superseded_gate BEFORE INSERT ON knowledge_claim_events WHEN NEW.state='superseded' BEGIN
SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM knowledge_claims c WHERE c.supersedes_claim_id=NEW.claim_id)
THEN RAISE(ABORT,'superseded claim requires a replacement claim') END; END""",
)
_IMMUTABLE=("catalog_models","catalog_sku_model_links","catalog_sku_model_events","knowledge_sources","knowledge_claims",
"knowledge_claim_evidence","knowledge_claim_reviews","knowledge_claim_events","knowledge_conflicts","knowledge_conflict_events")
for _table in _IMMUTABLE:
    _DDL += (f"CREATE TRIGGER {_table}_no_update BEFORE UPDATE ON {_table} BEGIN SELECT RAISE(ABORT,'knowledge records are append-only'); END",
             f"CREATE TRIGGER {_table}_no_delete BEFORE DELETE ON {_table} BEGIN SELECT RAISE(ABORT,'knowledge records are append-only'); END")
_REQUIRED_TRIGGERS={f"{t}_{a}" for t in _IMMUTABLE for a in ("no_update","no_delete")} | {
"knowledge_claim_subject_exists","knowledge_claim_supersedes_same_subject","knowledge_conflict_same_attribute",
"knowledge_claim_acceptance_gate","knowledge_claim_superseded_gate"}


def validate_knowledge(conn: sqlite3.Connection) -> None:
    """Reject missing, downgraded or structurally incomplete knowledge schemas."""
    tables={r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if not _TABLES.issubset(tables): raise RuntimeError("知识库数据表缺失；请运行知识库初始化")
    version=conn.execute("SELECT value FROM knowledge_meta WHERE key='schema_version'").fetchone()
    if not version or version[0]!=str(KNOWLEDGE_SCHEMA_VERSION): raise RuntimeError("知识库结构版本缺失或不受支持")
    triggers={r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='trigger'")}
    if not _REQUIRED_TRIGGERS.issubset(triggers): raise RuntimeError("知识库保护触发器缺失；拒绝继续操作")


def initialize_knowledge(path: str|Path=DEFAULT_DB) -> None:
    """Create V13 provenance tables transactionally without changing V10/V12 schemas."""
    with open_database(path) as conn:
        _validate_catalog(conn); conn.execute("BEGIN IMMEDIATE")
        try:
            has_meta=conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='knowledge_meta'").fetchone()
            objects={r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type IN ('table','trigger')")}
            partial={n for n in objects if n in _TABLES or n.startswith("knowledge_") or n.startswith("catalog_model")
                     or n.startswith("catalog_sku_model")}
            if has_meta:
                version=conn.execute("SELECT value FROM knowledge_meta WHERE key='schema_version'").fetchone()
                if not version or version[0]!=str(KNOWLEDGE_SCHEMA_VERSION): raise RuntimeError("检测到未知知识库版本，拒绝覆盖")
                validate_knowledge(conn); conn.execute("COMMIT"); return
            if partial: raise RuntimeError("发现未标记版本或不完整的知识库对象，拒绝自动接管")
            for statement in _DDL: conn.execute(statement)
            conn.execute("INSERT INTO knowledge_meta(key,value) VALUES('schema_version',?)",(str(KNOWLEDGE_SCHEMA_VERSION),))
            validate_knowledge(conn); conn.execute("COMMIT")
        except BaseException:
            if conn.in_transaction: conn.execute("ROLLBACK")
            raise


@contextmanager
def open_knowledge_readonly(path: str|Path=DEFAULT_DB) -> Iterator[sqlite3.Connection]:
    """Yield a verified read-only knowledge connection."""
    target=Path(path).expanduser().absolute()
    if target.is_symlink() or any(p.is_symlink() for p in target.parents) or not target.is_file():
        raise ValueError("数据库不存在或路径不安全；请先执行知识库初始化")
    conn=sqlite3.connect(target.as_uri()+"?mode=ro",uri=True,timeout=5); conn.execute("PRAGMA query_only=ON")
    try: validate_knowledge(conn); yield conn
    finally: conn.close()
