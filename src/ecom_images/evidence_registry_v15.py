"""V15 evidence registry: source hash, page anchors, variant/alias distinctions."""
from __future__ import annotations
import argparse, csv, hashlib, io, json, re, sqlite3, unicodedata
from pathlib import Path
from typing import Any
ALLOWED_TYPES={"exact_model_listed","family_variant_listed","candidate_alias","drawing_present","dimension_table_present"}
REVIEW_STATES={"human_page_reviewed","candidate_unconfirmed","transcription_pending_double_check","ocr_candidate"}
SHA=re.compile(r"[0-9a-f]{64}\Z")
SOURCE_ID=re.compile(r"[a-z0-9_.-]{3,100}\Z")
def norm_model(value:str)->str:
    return re.sub(r"\s+","",unicodedata.normalize("NFKC",value)).replace("–","-").replace("—","-").replace("−","-").upper()
def contains_exact_model(text:str,model:str)->bool:
    return re.search(r"(?<![A-Z0-9.\-])"+re.escape(norm_model(model))+r"(?![A-Z0-9.\-])",norm_model(text)) is not None
def canonical(v:Any)->str: return json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(",",":"),allow_nan=False)
def audit(history:dict,seed:dict)->dict:
    if history.get("meta",{}).get("version")!="13.0" or len(history.get("records",[]))!=74: raise ValueError("历史V13基线不符")
    records=history["records"];byid={r["id"]:r for r in records}
    if len(byid)!=len(records): raise ValueError("历史ID重复")
    if seed.get("version")!="15.0": raise ValueError("证据种子版本不是V15")
    sources=seed.get("sources");claims=seed.get("claims")
    if not isinstance(sources,list) or not isinstance(claims,list): raise ValueError("来源和断言必须为数组")
    sm={}
    for s in sources:
        if not isinstance(s,dict) or not SOURCE_ID.fullmatch(str(s.get("source_id",""))): raise ValueError("来源ID无效")
        if s["source_id"] in sm: raise ValueError("来源ID重复")
        if s.get("source_type")!="manufacturer_catalog" or not SHA.fullmatch(str(s.get("sha256",""))): raise ValueError("来源类型或SHA256无效")
        if type(s.get("size_bytes")) is not int or s["size_bytes"]<=0 or type(s.get("pdf_pages")) is not int or s["pdf_pages"]<=0: raise ValueError("来源文件元数据无效")
        sm[s["source_id"]]=s
    cids=set();unique=set();pages=set();byrec={};exactids=set();counts={t:0 for t in ALLOWED_TYPES}
    required={"claim_id","history_id","history_model","claim_type","value","source_id","pdf_page","printed_page_label","review_status","excerpt","related_model","notes"}
    for c in claims:
        if set(c)!=required: raise ValueError("断言字段不符合V15 schema")
        if not isinstance(c["claim_id"],str) or c["claim_id"] in cids: raise ValueError("断言ID缺失或重复")
        cids.add(c["claim_id"])
        if c["history_id"] not in byid: raise ValueError("孤立历史ID")
        r=byid[c["history_id"]]
        if c["history_model"]!=r["model"] or c["source_id"] not in sm: raise ValueError("型号或来源关联错误")
        if type(c["pdf_page"]) is not int or not 1<=c["pdf_page"]<=sm[c["source_id"]]["pdf_pages"]: raise ValueError("页码超范围")
        if c["claim_type"] not in ALLOWED_TYPES or c["review_status"] not in REVIEW_STATES: raise ValueError("证据类型/状态无效")
        if not isinstance(c["value"],str) or not c["value"].strip() or not isinstance(c["excerpt"],str) or not c["excerpt"].strip(): raise ValueError("证据值或摘录为空")
        key=(c["history_id"],c["claim_type"],c["value"],c["source_id"],c["pdf_page"])
        if key in unique: raise ValueError("重复同页断言")
        unique.add(key);counts[c["claim_type"]]+=1;pages.add(c["pdf_page"]);byrec.setdefault(c["history_id"],[]).append(c)
        if c["claim_type"]!="dimension_table_present" and not contains_exact_model(c["excerpt"],c["value"]): raise ValueError("证据摘录中未发现完整型号字符串")
        if c["claim_type"]=="exact_model_listed":
            if c["value"]!=r["model"]: raise ValueError("精确型号与历史记录不完全相同")
            if c["review_status"]!="human_page_reviewed": raise ValueError("精确型号必须人工核对")
            exactids.add(r["id"])
        elif c["claim_type"]=="family_variant_listed":
            if c["value"]==r["model"] or c["related_model"]!=r["model"] or not norm_model(c["value"]).startswith(norm_model(r["model"])): raise ValueError("系列变体关系无效")
        elif c["claim_type"]=="candidate_alias":
            if c["review_status"]!="candidate_unconfirmed" or c["related_model"]!=r["model"] or c["value"]==r["model"]: raise ValueError("候选别名必须未确认且关联正确")
        elif c["claim_type"]=="drawing_present" and c["review_status"]!="human_page_reviewed": raise ValueError("图纸存在性必须人工看图")
        elif c["claim_type"]=="dimension_table_present" and c["review_status"]!="transcription_pending_double_check": raise ValueError("尺寸表须保留双人复录状态")
    return {"ok":True,"history_records":len(records),"model_records":sum(r["record_type"]=="历史型号（SKU待绑定）" for r in records),"source_count":len(sm),"source_sha256_count":sum(bool(s["sha256"]) for s in sm.values()),"claims_count":len(claims),"unique_pdf_pages_reviewed":len(pages),"records_with_any_source_anchor":len(byrec),"records_with_exact_model_listed":len(exactids),"records_without_exact_model_anchor":len(records)-len(exactids),"claim_type_counts":counts,"independent_engineering_verifications":0,"confirmed_commercial_skus":0,"records":records,"claims_by_id":byrec,"source":next(iter(sm.values()))}
def export_claims_csv(report:dict)->bytes:
    f=io.StringIO(newline="");w=csv.writer(f);w.writerow(["历史ID","品类","系列","历史型号","记录类型","原件PDF页码","印刷页码","证据类型","证据值","审核状态","工程参数已核实","正式SKU已确认"])
    for r in report["records"]:
        for c in report["claims_by_id"].get(r["id"],[]) or [None]:
            vals=[r["id"],r["category"],r["series"],r["model"],r["record_type"],c["pdf_page"] if c else "",c["printed_page_label"] if c else "",c["claim_type"] if c else "",c["value"] if c else "",c["review_status"] if c else "无原件页码","否","否"]
            w.writerow(["'"+str(v) if isinstance(v,str) and v.lstrip().startswith(("=","+","-","@")) else v for v in vals])
    return ("\ufeff"+f.getvalue()).encode("utf-8")
def export_status_csv(report:dict)->bytes:
    f=io.StringIO(newline="");w=csv.writer(f);w.writerow(["历史ID","品类","系列","历史型号","记录类型","来源PDF页码","精确型号页码","系列变体","候选别名","图纸页码","证据状态","工程参数已核实","正式SKU已确认","下一步动作"])
    for r in report["records"]:
        cs=report["claims_by_id"].get(r["id"],[]);pages=sorted({c["pdf_page"] for c in cs});exact=sorted({c["pdf_page"] for c in cs if c["claim_type"]=="exact_model_listed"});variants=sorted({c["value"] for c in cs if c["claim_type"]=="family_variant_listed"});aliases=sorted({c["value"] for c in cs if c["claim_type"]=="candidate_alias"});drawings=sorted({c["pdf_page"] for c in cs if c["claim_type"]=="drawing_present"})
        if exact: status,action="原画册精确型号已定位；参数待核","取得受控图纸/BOM，工程复核参数，再绑定店铺SKU"
        elif aliases: status,action="候选别名待消歧；不得自动合并","核对包装标签、物料编码、原图与店铺SKU"
        elif variants: status,action="系列后缀已定位；基础型号未等同确认","逐个后缀补尺寸/BOM和真实SKU映射"
        elif cs: status,action="有来源锚点，但缺精确型号证据","补原件页码并人工确认型号关系"
        else: status,action="待补原始来源页码","查找原始图纸、产品标签或采购记录"
        vals=[r["id"],r["category"],r["series"],r["model"],r["record_type"],";".join(map(str,pages)),";".join(map(str,exact)),";".join(variants),";".join(aliases),";".join(map(str,drawings)),status,"否","否",action]
        w.writerow(["'"+str(v) if isinstance(v,str) and v.lstrip().startswith(("=","+","-","@")) else v for v in vals])
    return ("\ufeff"+f.getvalue()).encode("utf-8")
def verify_source_bytes(raw:bytes,source:dict)->dict:
    if not isinstance(raw,bytes) or not raw: raise ValueError("原始文件字节为空")
    digest=hashlib.sha256(raw).hexdigest()
    return {"sha256_matches":digest==source.get("sha256"),"size_matches":len(raw)==source.get("size_bytes"),"actual_sha256":digest,"actual_size_bytes":len(raw)}
def init_db(conn)->None:
    conn.execute("PRAGMA foreign_keys=ON");conn.execute("BEGIN IMMEDIATE")
    try:
        for q in [
          "CREATE TABLE IF NOT EXISTS evidence_v15_meta(key TEXT PRIMARY KEY,value TEXT NOT NULL)",
          "CREATE TABLE IF NOT EXISTS evidence_v15_history_snapshot(history_id TEXT PRIMARY KEY,model TEXT NOT NULL,category TEXT NOT NULL,series TEXT NOT NULL,record_type TEXT NOT NULL,payload_sha256 TEXT NOT NULL)",
          "CREATE TABLE IF NOT EXISTS evidence_v15_sources(source_id TEXT PRIMARY KEY,title TEXT NOT NULL,sha256 TEXT NOT NULL,size_bytes INTEGER NOT NULL CHECK(size_bytes>0),pdf_pages INTEGER NOT NULL CHECK(pdf_pages>0),source_json TEXT NOT NULL,source_json_sha256 TEXT NOT NULL)",
          "CREATE TABLE IF NOT EXISTS evidence_v15_claims(claim_id TEXT PRIMARY KEY,history_id TEXT NOT NULL REFERENCES evidence_v15_history_snapshot(history_id) ON DELETE RESTRICT,source_id TEXT NOT NULL REFERENCES evidence_v15_sources(source_id) ON DELETE RESTRICT,claim_type TEXT NOT NULL,value TEXT NOT NULL,pdf_page INTEGER NOT NULL CHECK(pdf_page>0),review_status TEXT NOT NULL,claim_json TEXT NOT NULL,claim_sha256 TEXT NOT NULL,UNIQUE(history_id,claim_type,value,source_id,pdf_page))",
          "CREATE INDEX IF NOT EXISTS idx_ev15_claim_history ON evidence_v15_claims(history_id,claim_type)",
          "CREATE INDEX IF NOT EXISTS idx_ev15_claim_page ON evidence_v15_claims(source_id,pdf_page)",
          "CREATE TRIGGER IF NOT EXISTS ev15_history_no_update BEFORE UPDATE ON evidence_v15_history_snapshot BEGIN SELECT RAISE(ABORT,'history snapshot is immutable'); END",
          "CREATE TRIGGER IF NOT EXISTS ev15_history_no_delete BEFORE DELETE ON evidence_v15_history_snapshot BEGIN SELECT RAISE(ABORT,'history snapshot is immutable'); END",
          "CREATE TRIGGER IF NOT EXISTS ev15_sources_no_update BEFORE UPDATE ON evidence_v15_sources BEGIN SELECT RAISE(ABORT,'evidence sources are immutable'); END",
          "CREATE TRIGGER IF NOT EXISTS ev15_sources_no_delete BEFORE DELETE ON evidence_v15_sources BEGIN SELECT RAISE(ABORT,'evidence sources are immutable'); END",
          "CREATE TRIGGER IF NOT EXISTS ev15_claims_no_update BEFORE UPDATE ON evidence_v15_claims BEGIN SELECT RAISE(ABORT,'claims are immutable; append a superseding claim'); END",
          "CREATE TRIGGER IF NOT EXISTS ev15_claims_no_delete BEFORE DELETE ON evidence_v15_claims BEGIN SELECT RAISE(ABORT,'claims cannot be deleted'); END"]: conn.execute(q)
        old=conn.execute("SELECT value FROM evidence_v15_meta WHERE key='schema_version'").fetchone()
        if old and old[0]!="15.0": raise RuntimeError("证据数据库版本冲突")
        conn.execute("INSERT OR IGNORE INTO evidence_v15_meta VALUES('schema_version','15.0')");conn.commit()
    except BaseException:
        conn.rollback();raise
def import_db(conn,history:dict,seed:dict,dry_run:bool=False)->dict:
    audit(history,seed);conn.execute("PRAGMA foreign_keys=ON")
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='evidence_v15_meta'").fetchone(): raise RuntimeError("先运行 db-init")
    version=conn.execute("SELECT value FROM evidence_v15_meta WHERE key='schema_version'").fetchone()
    if not version or version[0]!="15.0": raise RuntimeError("证据数据库版本无效")
    result={"history_added":0,"sources_added":0,"claims_added":0,"unchanged":0,"dry_run":dry_run};conn.execute("SAVEPOINT ev15_import")
    try:
        snap=hashlib.sha256(canonical(history).encode()).hexdigest();old=conn.execute("SELECT value FROM evidence_v15_meta WHERE key='history_snapshot_sha256'").fetchone()
        if old and old[0]!=snap: raise ValueError("历史基线变化；拒绝覆盖")
        count=conn.execute("SELECT count(*) FROM evidence_v15_history_snapshot").fetchone()[0]
        if count not in (0,len(history["records"])): raise ValueError("历史快照不完整")
        if not count:
            for r in history["records"]:
                digest=hashlib.sha256(canonical(r).encode()).hexdigest()
                conn.execute("INSERT INTO evidence_v15_history_snapshot VALUES(?,?,?,?,?,?)",(r["id"],r["model"],r["category"],r["series"],r["record_type"],digest));result["history_added"]+=1
            conn.execute("INSERT OR IGNORE INTO evidence_v15_meta VALUES('history_snapshot_sha256',?)",(snap,))
        for src in seed["sources"]:
            raw=canonical(src);digest=hashlib.sha256(raw.encode()).hexdigest();old=conn.execute("SELECT source_json_sha256 FROM evidence_v15_sources WHERE source_id=?",(src["source_id"],)).fetchone()
            if old:
                if old[0]!=digest: raise ValueError("来源冲突；不得覆盖")
                result["unchanged"]+=1;continue
            conn.execute("INSERT INTO evidence_v15_sources VALUES(?,?,?,?,?,?,?)",(src["source_id"],src["title"],src["sha256"],src["size_bytes"],src["pdf_pages"],raw,digest));result["sources_added"]+=1
        for c in seed["claims"]:
            raw=canonical(c);digest=hashlib.sha256(raw.encode()).hexdigest();old=conn.execute("SELECT claim_sha256 FROM evidence_v15_claims WHERE claim_id=?",(c["claim_id"],)).fetchone()
            if old:
                if old[0]!=digest: raise ValueError("证据断言冲突；不得覆写")
                result["unchanged"]+=1;continue
            conn.execute("INSERT INTO evidence_v15_claims VALUES(?,?,?,?,?,?,?,?,?)",(c["claim_id"],c["history_id"],c["source_id"],c["claim_type"],c["value"],c["pdf_page"],c["review_status"],raw,digest));result["claims_added"]+=1
        if dry_run: conn.execute("ROLLBACK TO SAVEPOINT ev15_import")
        conn.execute("RELEASE SAVEPOINT ev15_import");return result
    except BaseException:
        if conn.in_transaction: conn.execute("ROLLBACK TO SAVEPOINT ev15_import");conn.execute("RELEASE SAVEPOINT ev15_import")
        raise
def check_db(conn)->dict:
    problems=[]
    try:
        if conn.execute("PRAGMA quick_check").fetchone()[0]!="ok":problems.append("SQLite quick_check失败")
        if conn.execute("PRAGMA foreign_key_check").fetchall():problems.append("外键错误")
        for key,raw,digest in conn.execute("SELECT source_id,source_json,source_json_sha256 FROM evidence_v15_sources"):
            if hashlib.sha256(raw.encode()).hexdigest()!=digest:problems.append("来源摘要错误:"+key)
        for key,raw,digest in conn.execute("SELECT claim_id,claim_json,claim_sha256 FROM evidence_v15_claims"):
            if hashlib.sha256(raw.encode()).hexdigest()!=digest:problems.append("断言摘要错误:"+key)
        return {"ok":not problems,"history_records":conn.execute("SELECT count(*) FROM evidence_v15_history_snapshot").fetchone()[0],"sources":conn.execute("SELECT count(*) FROM evidence_v15_sources").fetchone()[0],"claims":conn.execute("SELECT count(*) FROM evidence_v15_claims").fetchone()[0],"problems":problems}
    except Exception as e:return {"ok":False,"problems":[str(e)]}
def main()->int:
    root=Path(__file__).resolve().parents[2];p=argparse.ArgumentParser(description="V15证据库；与正式SKU表隔离");p.add_argument("action",choices=["audit","db-init","db-import","db-check","find"],nargs="?",default="audit");p.add_argument("--database",type=Path,default=root/"data"/"evidence_v15.sqlite3");p.add_argument("--model",default="");p.add_argument("--dry-run",action="store_true");a=p.parse_args()
    history=json.loads((root/"assets/history/history_reference_v13.json").read_text(encoding="utf-8"));seed=json.loads((root/"assets/history/evidence_seed_v15.json").read_text(encoding="utf-8"))
    if a.action=="audit":
        r=audit(history,seed);out={k:v for k,v in r.items() if k not in {"records","claims_by_id","source"}}
    else:
        a.database.parent.mkdir(parents=True,exist_ok=True)
        with sqlite3.connect(a.database) as c:
            if a.action=="db-init":init_db(c);out={"ok":True,"action":"db-init"}
            elif a.action=="db-import":out=import_db(c,history,seed,a.dry_run)
            elif a.action=="db-check":out=check_db(c)
            else:
                q="SELECT h.model,h.category,c.claim_type,c.value,c.pdf_page,c.review_status FROM evidence_v15_history_snapshot h JOIN evidence_v15_claims c ON c.history_id=h.history_id WHERE h.model LIKE ? ORDER BY h.category,h.model,c.pdf_page"
                out=[dict(zip(("model","category","claim_type","value","pdf_page","review_status"),x)) for x in c.execute(q,("%"+a.model.replace("%","\\%").replace("_","\\_")+"%",))]
    print(json.dumps(out,ensure_ascii=False,indent=2));return 0 if not isinstance(out,dict) or out.get("ok",True) else 1
if __name__=="__main__":raise SystemExit(main())
