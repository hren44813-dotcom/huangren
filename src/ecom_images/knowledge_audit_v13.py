"""Read-only summaries and integrity checks for the V13 knowledge layer."""
from __future__ import annotations
import json,re
from pathlib import Path
from typing import Any
from .database_v9 import DEFAULT_DB
from .knowledge_schema_v13 import open_knowledge_readonly


def knowledge_summary(path: str|Path=DEFAULT_DB) -> dict[str,Any]:
    """Return table counts and latest claim, conflict and mapping states."""
    with open_knowledge_readonly(path) as conn:
        counts={k:conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for k,t in (
        ("models","catalog_models"),("model_links","catalog_sku_model_links"),("sources","knowledge_sources"),
        ("claims","knowledge_claims"),("evidence","knowledge_claim_evidence"),("reviews","knowledge_claim_reviews"),("conflicts","knowledge_conflicts"))}
        def latest_counts(table: str,key: str) -> dict[str,int]:
            """Count latest states in one internal append-only event table."""
            rows=conn.execute(f"""SELECT e.state,COUNT(*) FROM {table} e JOIN
            (SELECT {key},MAX(event_id) last_id FROM {table} GROUP BY {key}) x ON x.last_id=e.event_id GROUP BY e.state""").fetchall()
            return dict(rows)
        return {"schema_version":1,"counts":counts,"claim_states":latest_counts("knowledge_claim_events","claim_id"),
                "conflict_states":latest_counts("knowledge_conflict_events","conflict_id"),
                "mapping_states":latest_counts("catalog_sku_model_events","link_id")}


def list_claims(path: str|Path=DEFAULT_DB,*,subject_type: str="",subject_id: str="",attribute: str="",limit: int=100) -> list[dict[str,Any]]:
    """List claims with their latest state and evidence/review counts."""
    if not 1<=limit<=500 or (subject_type and subject_type not in {"model","product","sku","asset"}): raise ValueError("查询条件或条数无效")
    with open_knowledge_readonly(path) as conn:
        sql="""SELECT c.id,c.subject_type,c.subject_id,c.attribute,c.literal_value,c.unit,c.claim_kind,
        (SELECT state FROM knowledge_claim_events e WHERE e.claim_id=c.id ORDER BY e.event_id DESC LIMIT 1),
        (SELECT COUNT(*) FROM knowledge_claim_evidence e WHERE e.claim_id=c.id),
        (SELECT COUNT(*) FROM knowledge_claim_reviews r WHERE r.claim_id=c.id) FROM knowledge_claims c WHERE 1=1"""
        args=[]
        for col,val in (("subject_type",subject_type),("subject_id",subject_id),("attribute",attribute)):
            if val: sql+=f" AND c.{col}=?"; args.append(val)
        sql+=" ORDER BY c.created_utc DESC,c.id LIMIT ?"; args.append(limit)
        rows=conn.execute(sql,args).fetchall()
    keys=("claim_id","subject_type","subject_id","attribute","literal_value","unit","claim_kind","state","evidence_count","review_count")
    return [dict(zip(keys,row)) for row in rows]


def knowledge_audit(path: str|Path=DEFAULT_DB) -> dict[str,Any]:
    """Run read-only physical, referential and provenance-completeness checks."""
    findings=[]
    with open_knowledge_readonly(path) as conn:
        if conn.execute("PRAGMA quick_check").fetchone()[0]!="ok": findings.append("SQLite物理完整性检查失败")
        if conn.execute("PRAGMA foreign_key_check").fetchall(): findings.append("存在外键异常")
        for ident,digest,size,metadata in conn.execute("SELECT id,sha256,size_bytes,metadata_json FROM knowledge_sources"):
            if not re.fullmatch(r"[0-9a-f]{64}",digest) or size<=0: findings.append(f"原始资料{ident[:10]}的指纹或文件大小无效")
            try:
                if not isinstance(json.loads(metadata),dict): raise ValueError("not object")
            except (ValueError,TypeError): findings.append(f"原始资料{ident[:10]}的元数据JSON无效")
        for ident,region in conn.execute("SELECT id,region_json FROM knowledge_claim_evidence"):
            try:
                if not isinstance(json.loads(region),dict): raise ValueError("not object")
            except (ValueError,TypeError): findings.append(f"证据{ident[:10]}的区域定位JSON无效")
        missing=conn.execute("""SELECT COUNT(*) FROM knowledge_claims c LEFT JOIN knowledge_claim_evidence e
        ON e.claim_id=c.id WHERE e.id IS NULL""").fetchone()[0]
        invalid_accepted=conn.execute("""SELECT COUNT(*) FROM knowledge_claim_events e
        JOIN (SELECT claim_id,MAX(event_id) last_id FROM knowledge_claim_events GROUP BY claim_id) x ON x.last_id=e.event_id
        WHERE e.state='accepted' AND (
        NOT EXISTS(SELECT 1 FROM knowledge_claim_evidence v WHERE v.claim_id=e.claim_id AND v.evidence_role='supports')
        OR NOT EXISTS(SELECT 1 FROM knowledge_claim_reviews r WHERE r.claim_id=e.claim_id AND r.verdict='supports'
          AND r.reviewer_role IN ('second_reviewer','manufacturer','independent_lab'))
        OR EXISTS(SELECT 1 FROM knowledge_claim_reviews r WHERE r.claim_id=e.claim_id AND r.verdict='contradicts')
        OR EXISTS(SELECT 1 FROM knowledge_claim_evidence v WHERE v.claim_id=e.claim_id AND v.evidence_role='contradicts'))""").fetchone()[0]
    if missing: findings.append(f"有{missing}条参数主张尚无来源定位")
    if invalid_accepted: findings.append(f"有{invalid_accepted}条已接受主张不再满足证据/复核门槛")
    return {"ok":not findings,"findings":findings[:100],"additional_findings":max(0,len(findings)-100),
            "claims_without_evidence":missing,"accepted_claims_outside_gate":invalid_accepted,"summary":knowledge_summary(path)}
