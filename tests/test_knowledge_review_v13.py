from __future__ import annotations
import csv,hashlib,io,sqlite3,sys,tempfile,unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
import fitz
from ecom_images.catalog_v12 import COLUMNS,import_catalog_csv
from ecom_images.database_v9 import open_database,save_job
from ecom_images.production_ledger_v6 import new_record
from ecom_images.knowledge_schema_v13 import initialize_knowledge
from ecom_images.knowledge_v13 import add_model
from ecom_images.knowledge_claims_v13 import create_claim,create_conflict,transition_conflict
from ecom_images.knowledge_ingest_v13 import import_document,initialize_ingestion,search_knowledge
from ecom_images.knowledge_review_v13 import (
    create_claim_from_segment,get_claim_review_detail,list_open_conflicts,list_review_claims,
    list_review_sources,record_claim_review,render_segment_preview,
)

def catalog_csv():
    row={"店铺编码":"SHOP-1","店铺名称":"工业五金店","平台":"天猫","商品编码":"P-1","商品名称":"测试转轴",
    "商品类别":"阻尼转轴","SKU编码":"SKU-1","产品型号":"GL1-336","材质":"","表面处理":"","孔距(mm)":"","总长(mm)":"","备注":""}
    stream=io.StringIO(newline=""); writer=csv.DictWriter(stream,fieldnames=COLUMNS); writer.writeheader(); writer.writerow(row)
    return ("\ufeff"+stream.getvalue()).encode("utf-8")

class KnowledgeReviewV13Tests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name); self.db=self.root/"knowledge.sqlite3"
        save_job(self.db,new_record([("SKU.jpg",b"synthetic",{})],fingerprint="a"*64,platform="天猫",template="蓝白"))
        import_catalog_csv(self.db,catalog_csv(),dry_run=False)
        initialize_knowledge(self.db); initialize_ingestion(self.db)
        self.inputs=self.root/"inputs"; self.inputs.mkdir()
        self.model_id=add_model(self.db,model_code="GL1-336",category="阻尼转轴",manufacturer_name="测试制造商")
    def write_pdf(self):
        path=self.inputs/"catalog.pdf"; doc=fitz.open()
        page=doc.new_page(width=595,height=842)
        page.insert_text((50,70),"Model GL1-336")
        page.insert_text((50,105),"Rated torque 6 N.m")
        page.insert_text((50,140),"Material SUS304")
        doc.save(path); doc.close(); return path
    def import_pdf(self):
        return import_document(self.db,file_path=self.write_pdf(),source_kind="manufacturer_document",
            authority_level="manufacturer_controlled",document_family="GL1-336")
    def segment(self,*,attribute="Torque",exact_model=True):
        query={"model_code":"GL1-336"} if exact_model else {"query":"扭矩"}
        if attribute: query["attribute"]=attribute
        docs=[x for x in search_knowledge(self.db,**query)["results"] if x["type"]=="document"]
        self.assertTrue(docs)
        return next((x for x in docs if x["segment_type"] in {"pdf_page","markdown_section"}),docs[0])
    def create_from_pdf(self):
        self.import_pdf(); seg=self.segment()
        result=create_claim_from_segment(self.db,segment_id=seg["segment_id"],model_id=self.model_id,
            attribute="Torque",literal_value="6",unit="N.m",claim_kind="catalog_transcription",created_by="运营")
        return seg,result
    def test_create_claim_and_evidence_atomically_preserves_source_location(self):
        seg,result=self.create_from_pdf()
        self.assertEqual(result["state"],"proposed")
        self.assertTrue(result["claim_id"])
        detail=get_claim_review_detail(self.db,claim_id=result["claim_id"])
        self.assertEqual(detail["claim"]["state"],"proposed")
        self.assertEqual(len(detail["evidence"]),1)
        evidence=detail["evidence"][0]
        self.assertEqual(evidence["source_id"],seg["source_id"])
        self.assertEqual(evidence["pdf_page"],1)
        self.assertEqual(evidence["region"]["segment_id"],seg["segment_id"])
        self.assertEqual(evidence["region"]["bbox"],seg["location"]["region"]["bbox"])
        self.assertIn("Rated torque",evidence["literal_excerpt"])
        self.assertEqual(list_review_claims(self.db,model_code="GL1-336",attribute="Torque")[0]["claim_id"],result["claim_id"])
    def test_tampered_source_blocks_claim_and_leaves_no_partial_rows(self):
        imported=self.import_pdf(); seg=self.segment()
        stored=self.root/imported["storage_relpath"]; stored.write_bytes(stored.read_bytes()+b"tamper")
        with self.assertRaisesRegex(ValueError,"SHA-256"):
            create_claim_from_segment(self.db,segment_id=seg["segment_id"],model_id=self.model_id,
                attribute="扭矩",literal_value="6",unit="N.m",claim_kind="catalog_transcription",created_by="运营")
        with open_database(self.db) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM knowledge_claims").fetchone()[0],0)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM knowledge_claim_evidence").fetchone()[0],0)
    def test_pdf_preview_returns_page_image_and_highlighted_region(self):
        self.import_pdf(); seg=self.segment(attribute="",exact_model=True)
        preview=render_segment_preview(self.db,segment_id=seg["segment_id"])
        self.assertTrue(preview["available"])
        self.assertEqual(preview["pdf_page"],1)
        self.assertTrue(preview["highlighted"])
        self.assertTrue(preview["png"].startswith(b"\x89PNG\r\n\x1a\n"))
        self.assertEqual(preview["source_sha256"],hashlib.sha256((self.root/preview["storage_relpath"]).read_bytes()).hexdigest())
    def test_preview_fails_closed_when_source_file_is_changed(self):
        imported=self.import_pdf(); seg=self.segment(attribute="",exact_model=True)
        stored=self.root/imported["storage_relpath"]; stored.write_bytes(stored.read_bytes()+b"tamper")
        with self.assertRaisesRegex(ValueError,"SHA-256"):
            render_segment_preview(self.db,segment_id=seg["segment_id"])
    def test_acceptance_and_review_are_atomic_and_require_independent_reviewer(self):
        _,result=self.create_from_pdf(); claim_id=result["claim_id"]
        with self.assertRaisesRegex(ValueError,"independent supporting review"):
            record_claim_review(self.db,claim_id=claim_id,verdict="supports",reviewer_role="author",
                reviewer_name="录入人",method="自查",notes="看起来一致",decision_state="accepted",
                actor="审核人",decision_note="尝试接受")
        detail=get_claim_review_detail(self.db,claim_id=claim_id)
        self.assertEqual(detail["claim"]["state"],"proposed")
        self.assertEqual(detail["reviews"],[])
        record_claim_review(self.db,claim_id=claim_id,verdict="supports",reviewer_role="second_reviewer",
            reviewer_name="独立复核",method="对照原始页",notes="参数与原文一致",
            decision_state="accepted",actor="质量审核",decision_note="证据与独立复核满足门槛")
        detail=get_claim_review_detail(self.db,claim_id=claim_id)
        self.assertEqual(detail["claim"]["state"],"accepted")
        self.assertEqual(len(detail["reviews"]),1)
    def test_contradictory_review_reopens_accepted_claim(self):
        _,result=self.create_from_pdf(); claim_id=result["claim_id"]
        record_claim_review(self.db,claim_id=claim_id,verdict="supports",reviewer_role="second_reviewer",
            reviewer_name="工程复核",method="核对原图",notes="支持",decision_state="accepted",actor="审核人")
        record_claim_review(self.db,claim_id=claim_id,verdict="contradicts",reviewer_role="manufacturer",
            reviewer_name="制造商",method="书面回复",notes="制造商给出的扭矩不同")
        detail=get_claim_review_detail(self.db,claim_id=claim_id)
        self.assertEqual(detail["claim"]["state"],"reopened")
        self.assertEqual(len(detail["reviews"]),2)
    def test_non_pdf_locator_is_saved_without_fake_page_number(self):
        path=self.inputs/"spec.md"
        path.write_text("# GL1-336\n额定扭矩：6 N.m\n",encoding="utf-8")
        import_document(self.db,file_path=path,source_kind="manufacturer_document")
        seg=self.segment(attribute="扭矩")
        result=create_claim_from_segment(self.db,segment_id=seg["segment_id"],model_id=self.model_id,
            attribute="扭矩",literal_value="6",unit="N.m",claim_kind="catalog_transcription",created_by="运营")
        evidence=get_claim_review_detail(self.db,claim_id=result["claim_id"])["evidence"][0]
        self.assertIsNone(evidence["pdf_page"])
        self.assertIsNotNone(evidence["region"]["line_start"])
        self.assertEqual(evidence["region"]["segment_type"],seg["segment_type"])
    def test_unknown_model_and_segment_fail_without_partial_claim(self):
        self.import_pdf(); seg=self.segment()
        with self.assertRaisesRegex(ValueError,"制造商型号"):
            create_claim_from_segment(self.db,segment_id=seg["segment_id"],model_id="missing",
                attribute="扭矩",literal_value="6",unit="N.m",claim_kind="catalog_transcription",created_by="运营")
        with self.assertRaisesRegex(ValueError,"索引片段"):
            create_claim_from_segment(self.db,segment_id="missing",model_id=self.model_id,
                attribute="扭矩",literal_value="6",unit="N.m",claim_kind="catalog_transcription",created_by="运营")
        with open_database(self.db) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM knowledge_claims").fetchone()[0],0)
    def test_open_conflicts_show_both_values_and_filter_by_model_attribute(self):
        imported=self.import_pdf()
        first=create_claim(self.db,subject_type="model",subject_id=self.model_id,attribute="扭矩",
            literal_value="6",unit="N.m",claim_kind="catalog_transcription",created_by="运营")
        second=create_claim(self.db,subject_type="model",subject_id=self.model_id,attribute="扭矩",
            literal_value="7",unit="N.m",claim_kind="supplier_assertion",created_by="运营")
        create_conflict(self.db,claim_a_id=first,claim_b_id=second,created_by="运营",description="两份资料扭矩不同")
        conflicts=list_open_conflicts(self.db,model_code="GL1-336",attribute="扭矩")
        self.assertEqual(len(conflicts),1)
        self.assertEqual({conflicts[0]["claim_a"]["literal_value"],conflicts[0]["claim_b"]["literal_value"]},{"6","7"})
        self.assertEqual(list_open_conflicts(self.db,model_code="GL1-336",attribute="材质"),[])
        self.assertEqual(list_review_sources(self.db)[0]["source_id"],imported["source_id"])
    def test_review_queue_keeps_unconfirmed_sku_model_text_separate(self):
        with open_database(self.db) as conn:
            sku_id=conn.execute("SELECT id FROM catalog_skus WHERE code='SKU-1'").fetchone()[0]
        create_claim(self.db,subject_type="sku",subject_id=sku_id,attribute="扭矩",literal_value="6",
            unit="N.m",claim_kind="catalog_transcription",created_by="运营")
        row=list_review_claims(self.db,model_code="GL1-336",attribute="扭矩")[0]
        self.assertEqual(row["model_code"],"")
        self.assertEqual(row["sku_model_text"],"GL1-336")
        self.assertEqual(row["model_binding_status"],"sku_free_text_unverified")

    def test_review_detail_includes_review_history_and_evidence(self):
        _,result=self.create_from_pdf()
        record_claim_review(self.db,claim_id=result["claim_id"],verdict="inconclusive",reviewer_role="other",
            reviewer_name="审核人",method="待确认",notes="图中文字模糊")
        detail=get_claim_review_detail(self.db,claim_id=result["claim_id"])
        self.assertEqual(detail["reviews"][0]["verdict"],"inconclusive")
        self.assertEqual(detail["evidence"][0]["role"],"supports")
    def test_conflict_resolution_requires_source_and_removes_open_conflict(self):
        imported=self.import_pdf()
        first=create_claim(self.db,subject_type="model",subject_id=self.model_id,attribute="扭矩",
            literal_value="6",unit="N.m",claim_kind="catalog_transcription",created_by="运营")
        second=create_claim(self.db,subject_type="model",subject_id=self.model_id,attribute="扭矩",
            literal_value="7",unit="N.m",claim_kind="supplier_assertion",created_by="运营")
        conflict=create_conflict(self.db,claim_a_id=first,claim_b_id=second,created_by="运营",
            description="两个来源的扭矩值不一致")
        self.assertEqual(len(list_open_conflicts(self.db,model_code="GL1-336",attribute="扭矩")),1)
        with self.assertRaisesRegex(ValueError,"必须提供来源"):
            transition_conflict(self.db,conflict_id=conflict,state="resolved",actor="工程复核",
                resolution_note="已核对，采用制造商资料")
        transition_conflict(self.db,conflict_id=conflict,state="resolved",actor="工程复核",
            resolution_note="已核对登记的制造商资料，采用其扭矩值",source_id=imported["source_id"])
        self.assertEqual(list_open_conflicts(self.db,model_code="GL1-336",attribute="扭矩"),[])

if __name__=="__main__": unittest.main(verbosity=2)
