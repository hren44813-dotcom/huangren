"""V13 data model, provenance gates and migration-safety regression tests."""
from __future__ import annotations
import csv,hashlib,io,sqlite3,subprocess,sys,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT/"src"))
from ecom_images.catalog_v12 import COLUMNS,import_catalog_csv,list_skus
from ecom_images.database_v9 import open_database,save_job
from ecom_images.production_ledger_v6 import new_record
from ecom_images.knowledge_schema_v13 import initialize_knowledge
from ecom_images.knowledge_v13 import add_model,register_source,register_source_file,link_sku_model,set_sku_model_link_state,list_models
from ecom_images.knowledge_claims_v13 import create_claim,add_claim_evidence,add_claim_review,transition_claim,create_conflict,transition_conflict
from ecom_images.knowledge_audit_v13 import knowledge_audit,knowledge_summary,list_claims


def csv_rows():
    """Build a synthetic SKU row for isolated database tests."""
    row={"店铺编码":"SHOP-1","店铺名称":"工业五金店","平台":"天猫","商品编码":"P-1","商品名称":"测试转轴",
    "商品类别":"阻尼转轴","SKU编码":"SKU-1","产品型号":"GL1-336","材质":"","表面处理":"","孔距(mm)":"","总长(mm)":"","备注":""}
    stream=io.StringIO(newline=""); writer=csv.DictWriter(stream,fieldnames=COLUMNS); writer.writeheader(); writer.writerow(row)
    return ("\ufeff"+stream.getvalue()).encode("utf-8")


class KnowledgeV13Tests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name); self.db=self.root/"knowledge.sqlite3"
        self.job=new_record([("SKU.jpg",b"synthetic",{})],fingerprint="a"*64,platform="天猫",template="蓝白")
        save_job(self.db,self.job); import_catalog_csv(self.db,csv_rows(),dry_run=False)
        initialize_knowledge(self.db); initialize_knowledge(self.db)
        self.sku_id=list_skus(self.db)[0]["sku_id"]
        self.model_id=add_model(self.db,model_code="GL1-336",category="阻尼转轴",manufacturer_name="汇成五金")
        self.source_id=self.source(b"manufacturer catalog")
    def source(self,data,**overrides):
        """Register synthetic bytes with their computed digest."""
        options={"filename":"catalog.pdf","source_kind":"manufacturer_document","authority_level":"user_supplied",
        "sha256":hashlib.sha256(data).hexdigest(),"size_bytes":len(data),"page_count":10,
        "document_family":"GL1 catalog","revision_label":"unverified"}
        options.update(overrides); return register_source(self.db,**options)

    def test_additive_initialization_preserves_legacy_job_and_versions(self):
        with open_database(self.db) as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM jobs").fetchone()[0],1)
            self.assertEqual(c.execute("PRAGMA user_version").fetchone()[0],2)
            self.assertEqual(c.execute("SELECT value FROM catalog_meta WHERE key='schema_version'").fetchone()[0],"1")
            self.assertEqual(c.execute("SELECT value FROM knowledge_meta WHERE key='schema_version'").fetchone()[0],"1")
    def test_model_creation_is_idempotent_but_conflicting_metadata_fails(self):
        self.assertEqual(add_model(self.db,model_code="GL1-336",category="阻尼转轴",manufacturer_name="汇成五金"),self.model_id)
        with self.assertRaisesRegex(ValueError,"不一致"): add_model(self.db,model_code="GL1-336",category="铰链",manufacturer_name="汇成五金")
    def test_existing_sku_model_text_does_not_auto_link(self):
        self.assertEqual(list_models(self.db)[0]["sku_mapping_count"],0)
    def test_mapping_requires_source_and_note_to_confirm(self):
        link=link_sku_model(self.db,sku_id=self.sku_id,model_id=self.model_id,actor="运营",note="标签待核")
        with self.assertRaisesRegex(ValueError,"证据来源"): set_sku_model_link_state(self.db,link_id=link,state="confirmed",actor="审核人",note="已核实")
        set_sku_model_link_state(self.db,link_id=link,state="confirmed",actor="审核人",note="BOM已对照",source_id=self.source_id)
        self.assertEqual(knowledge_summary(self.db)["mapping_states"],{"confirmed":1})
        with self.assertRaises(sqlite3.IntegrityError):
            with open_database(self.db) as c: c.execute("UPDATE catalog_sku_model_events SET note='改写'")
    def test_source_file_hashes_real_bytes_and_does_not_store_them(self):
        source_file=self.root/"raw.txt"; source_file.write_bytes(b"original source bytes")
        ident=register_source_file(self.db,file_path=source_file,source_kind="internal_note",authority_level="user_supplied")
        with open_database(self.db) as c:
            row=c.execute("SELECT sha256,size_bytes FROM knowledge_sources WHERE id=?",(ident,)).fetchone()
            self.assertEqual(row[0],hashlib.sha256(b"original source bytes").hexdigest())
            self.assertEqual(row[1],len(b"original source bytes"))
            self.assertNotIn("content_blob",{x[1] for x in c.execute("PRAGMA table_info(knowledge_sources)")})
    def test_source_duplicate_with_different_authority_is_rejected(self):
        with self.assertRaisesRegex(ValueError,"元数据不一致"): self.source(b"manufacturer catalog",authority_level="manufacturer_controlled")
    def test_source_rejects_invalid_hash_path_and_date(self):
        with self.assertRaisesRegex(ValueError,"SHA-256"):
            register_source(self.db,filename="bad.pdf",source_kind="other",authority_level="unverified",sha256="x",size_bytes=1)
        with self.assertRaisesRegex(ValueError,"相对路径"):
            register_source(self.db,filename="bad.pdf",source_kind="other",authority_level="unverified",
                sha256=hashlib.sha256(b"bad").hexdigest(),size_bytes=3,storage_ref="../outside.pdf")
        with self.assertRaisesRegex(ValueError,"YYYY-MM-DD"): self.source(b"bad-date",issue_date="2026/10/01")
    def test_source_revisions_are_linked_without_overwriting(self):
        newer=self.source(b"new controlled revision",filename="catalog-r2.pdf",revision_label="R2",
            authority_level="manufacturer_controlled",supersedes_source_id=self.source_id)
        with open_database(self.db) as c:
            self.assertEqual(c.execute("SELECT supersedes_source_id FROM knowledge_sources WHERE id=?",(newer,)).fetchone()[0],self.source_id)
    def test_claim_cannot_target_nonexistent_subject(self):
        with self.assertRaisesRegex(ValueError,"无法创建参数主张"):
            create_claim(self.db,subject_type="model",subject_id="missing",attribute="扭矩",literal_value="6",
                claim_kind="catalog_transcription",created_by="运营",unit="N.m")
    def test_claim_needs_evidence_and_independent_review_before_acceptance(self):
        claim=create_claim(self.db,subject_type="model",subject_id=self.model_id,attribute="扭矩",literal_value="6",
            normalized_value=6,unit="N.m",claim_kind="catalog_transcription",created_by="运营")
        with self.assertRaisesRegex(ValueError,"状态校验"): transition_claim(self.db,claim_id=claim,state="accepted",actor="运营")
        add_claim_evidence(self.db,claim_id=claim,source_id=self.source_id,evidence_role="supports",extraction_method="manual",
            created_by="运营",pdf_page=37,printed_page="24",region={"bbox":[1,2,3,4]},literal_excerpt="扭矩 N.m")
        with self.assertRaisesRegex(ValueError,"状态校验"): transition_claim(self.db,claim_id=claim,state="accepted",actor="运营")
        add_claim_review(self.db,claim_id=claim,verdict="supports",reviewer_role="second_reviewer",reviewer_name="工程复核",method="对照原图",notes="读数一致")
        transition_claim(self.db,claim_id=claim,state="accepted",actor="质量审核")
        row=list_claims(self.db,subject_id=self.model_id)[0]
        self.assertEqual(row["state"],"accepted"); self.assertEqual(row["evidence_count"],1)
    def test_contradicting_review_blocks_acceptance(self):
        claim=create_claim(self.db,subject_type="model",subject_id=self.model_id,attribute="材质",literal_value="1215",claim_kind="catalog_transcription",created_by="运营")
        add_claim_evidence(self.db,claim_id=claim,source_id=self.source_id,evidence_role="supports",extraction_method="manual",created_by="运营")
        add_claim_review(self.db,claim_id=claim,verdict="supports",reviewer_role="second_reviewer",reviewer_name="A",method="复核",notes="支持")
        add_claim_review(self.db,claim_id=claim,verdict="contradicts",reviewer_role="manufacturer",reviewer_name="B",method="制造商回复",notes="不一致")
        with self.assertRaisesRegex(ValueError,"状态校验"): transition_claim(self.db,claim_id=claim,state="accepted",actor="审核人")
    def test_new_contradiction_reopens_an_accepted_claim(self):
        claim=create_claim(self.db,subject_type="model",subject_id=self.model_id,attribute="孔距",literal_value="23",claim_kind="catalog_transcription",created_by="运营")
        add_claim_evidence(self.db,claim_id=claim,source_id=self.source_id,evidence_role="supports",extraction_method="manual",created_by="运营")
        add_claim_review(self.db,claim_id=claim,verdict="supports",reviewer_role="second_reviewer",reviewer_name="A",method="复核",notes="支持")
        transition_claim(self.db,claim_id=claim,state="accepted",actor="审核人")
        add_claim_review(self.db,claim_id=claim,verdict="contradicts",reviewer_role="manufacturer",reviewer_name="B",method="制造商回复",notes="数据冲突")
        self.assertEqual(list_claims(self.db,subject_id=self.model_id,attribute="孔距")[0]["state"],"reopened")
    def test_claims_are_append_only(self):
        claim=create_claim(self.db,subject_type="model",subject_id=self.model_id,attribute="材质",literal_value="1215",claim_kind="catalog_transcription",created_by="运营")
        with self.assertRaises(sqlite3.IntegrityError):
            with open_database(self.db) as c: c.execute("UPDATE knowledge_claims SET literal_value='304' WHERE id=?",(claim,))
        with self.assertRaises(sqlite3.IntegrityError):
            with open_database(self.db) as c: c.execute("DELETE FROM knowledge_claims WHERE id=?",(claim,))
    def test_replacement_claim_must_match_subject_and_attribute(self):
        old=create_claim(self.db,subject_type="model",subject_id=self.model_id,attribute="扭矩",literal_value="6",claim_kind="catalog_transcription",created_by="运营")
        other=create_claim(self.db,subject_type="model",subject_id=self.model_id,attribute="材质",literal_value="1215",claim_kind="catalog_transcription",created_by="运营")
        with self.assertRaisesRegex(ValueError,"无法创建参数主张"):
            create_claim(self.db,subject_type="model",subject_id=self.model_id,attribute="扭矩",literal_value="7",claim_kind="supplier_assertion",created_by="运营",supersedes_claim_id=other)
        new=create_claim(self.db,subject_type="model",subject_id=self.model_id,attribute="扭矩",literal_value="7",claim_kind="supplier_assertion",created_by="运营",supersedes_claim_id=old)
        transition_claim(self.db,claim_id=old,state="superseded",actor="审核人",note="新版本替代")
        self.assertNotEqual(old,new)
    def test_conflict_requires_same_subject_attribute_and_source_to_resolve(self):
        a=create_claim(self.db,subject_type="model",subject_id=self.model_id,attribute="扭矩",literal_value="6 N.m",claim_kind="catalog_transcription",created_by="运营")
        b=create_claim(self.db,subject_type="model",subject_id=self.model_id,attribute="扭矩",literal_value="kgf·cm",claim_kind="manual_observation",created_by="运营")
        conflict=create_conflict(self.db,claim_a_id=a,claim_b_id=b,created_by="运营",description="单位冲突")
        with self.assertRaisesRegex(ValueError,"必须提供来源"): transition_conflict(self.db,conflict_id=conflict,state="resolved",actor="工程师",resolution_note="已核对")
        transition_conflict(self.db,conflict_id=conflict,state="resolved",actor="工程师",resolution_note="以受控图纸R2为准",source_id=self.source_id)
        self.assertEqual(knowledge_summary(self.db)["conflict_states"],{"resolved":1})
        with self.assertRaises(sqlite3.IntegrityError):
            with open_database(self.db) as c: c.execute("DELETE FROM knowledge_conflict_events")
    def test_conflict_rejects_different_attributes(self):
        a=create_claim(self.db,subject_type="model",subject_id=self.model_id,attribute="扭矩",literal_value="6",claim_kind="catalog_transcription",created_by="运营")
        b=create_claim(self.db,subject_type="model",subject_id=self.model_id,attribute="材质",literal_value="1215",claim_kind="catalog_transcription",created_by="运营")
        with self.assertRaisesRegex(ValueError,"同一对象"): create_conflict(self.db,claim_a_id=a,claim_b_id=b,created_by="运营",description="不同参数")
    def test_audit_reports_claims_without_evidence(self):
        create_claim(self.db,subject_type="model",subject_id=self.model_id,attribute="孔距",literal_value="23",claim_kind="catalog_transcription",created_by="运营")
        report=knowledge_audit(self.db); self.assertFalse(report["ok"]); self.assertEqual(report["claims_without_evidence"],1)
    def test_read_only_audit_does_not_create_missing_database(self):
        missing=self.root/"missing.sqlite3"
        with self.assertRaises(ValueError): knowledge_audit(missing)
        self.assertFalse(missing.exists())
    def test_cli_check_and_model_command(self):
        cli=[sys.executable,str(ROOT/"scripts/knowledge_admin_v13.py"),"--database",str(self.db)]
        result=subprocess.run(cli+["check"],cwd=ROOT,text=True,capture_output=True,timeout=20)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        added=subprocess.run(cli+["add-model","--code","MS705","--category","转舌锁"],cwd=ROOT,text=True,capture_output=True,timeout=20)
        self.assertEqual(added.returncode,0,added.stdout+added.stderr)


if __name__=="__main__": unittest.main(verbosity=2)
