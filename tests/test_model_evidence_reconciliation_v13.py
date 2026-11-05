"""Regression tests for exact model reconciliation, source conflicts and pre-render gates."""
from __future__ import annotations

import contextlib
import csv
import io
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

import fitz
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ecom_images.catalog_v12 import COLUMNS, import_catalog_csv
from ecom_images.database_v9 import open_database, save_job
from ecom_images.generator import build_job
from ecom_images.knowledge_ingest_v13 import import_document, initialize_ingestion, search_knowledge
from ecom_images.knowledge_review_v13 import create_claim_from_segment, record_claim_review
from ecom_images.knowledge_schema_v13 import initialize_knowledge
from ecom_images.knowledge_v13 import add_model, link_sku_model, set_sku_model_link_state
from ecom_images.model_evidence_reconciliation_v13 import (
    evaluate_content_gate, normalize_model_code, reconcile_model_evidence,
)
from ecom_images.production_ledger_v6 import new_record


def _catalog_csv() -> bytes:
    row = {
        "店铺编码": "SHOP-1", "店铺名称": "工业五金店", "平台": "天猫",
        "商品编码": "P-1", "商品名称": "测试阻尼转轴", "商品类别": "阻尼转轴",
        "SKU编码": "SKU-1", "产品型号": "GL1-336", "材质": "", "表面处理": "",
        "孔距(mm)": "", "总长(mm)": "", "备注": "",
    }
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=COLUMNS)
    writer.writeheader()
    writer.writerow(row)
    return ("\ufeff" + stream.getvalue()).encode("utf-8")


class ModelEvidenceReconciliationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.db = self.root / "knowledge.sqlite3"
        save_job(self.db, new_record(
            [("seed.jpg", b"synthetic", {})], fingerprint="a" * 64,
            platform="天猫", template="蓝白",
        ))
        import_catalog_csv(self.db, _catalog_csv(), dry_run=False)
        initialize_knowledge(self.db)
        initialize_ingestion(self.db)
        self.model_id = add_model(
            self.db, model_code="GL1-336", category="阻尼转轴",
            manufacturer_name="测试制造商",
        )
        with open_database(self.db) as conn:
            self.sku_id = conn.execute(
                "SELECT id FROM catalog_skus WHERE code='SKU-1'"
            ).fetchone()[0]

    def write_pdf(self, name="manufacturer.pdf", *, model="GL1-336", torque="6 N.m"):
        path = self.root / name
        doc = fitz.open()
        page = doc.new_page(width=595, height=842)
        page.insert_text((50, 70), f"Model {model}")
        page.insert_text((50, 105), f"Rated torque {torque}")
        page.insert_text((50, 140), "This page is test fixture data.")
        doc.save(path)
        doc.close()
        return path

    def import_pdf(self, name="manufacturer.pdf", *, model="GL1-336", torque="6 N.m",
                   authority="manufacturer_controlled", kind="manufacturer_document"):
        return import_document(
            self.db, file_path=self.write_pdf(name, model=model, torque=torque),
            source_kind=kind, authority_level=authority, document_family="GL1-336 test catalog",
        )

    def segment_for(self, source_id):
        result = search_knowledge(self.db, model_code="GL1-336", attribute="Torque")
        matches = [
            item for item in result["results"]
            if item.get("type") == "document" and item.get("source_id") == source_id
        ]
        self.assertTrue(matches, "source PDF should produce a searchable segment")
        return next(
            (item for item in matches if item.get("segment_type") in {"pdf_page", "markdown_section"}),
            matches[0],
        )

    def accepted_claim(self, imported, value):
        segment = self.segment_for(imported["source_id"])
        result = create_claim_from_segment(
            self.db, segment_id=segment["segment_id"], model_id=self.model_id,
            attribute="Torque", literal_value=value, unit="N.m",
            claim_kind="catalog_transcription", created_by="operator",
        )
        record_claim_review(
            self.db, claim_id=result["claim_id"], verdict="supports",
            reviewer_role="second_reviewer", reviewer_name="independent reviewer",
            method="compare against original source page", notes="value and source location checked",
            decision_state="accepted", actor="quality reviewer",
            decision_note="source and independent review requirements met",
        )
        return result["claim_id"]

    def test_model_code_normalization_preserves_variant_suffix(self):
        self.assertEqual(normalize_model_code(" GL1 – 336 "), "GL1-336")
        report = reconcile_model_evidence(self.db, model_code="GL1-336")
        self.assertTrue(report["model_found"])
        self.assertEqual(report["model_identity_count"], 1)

    def test_supplier_text_match_is_candidate_not_confirmed_mapping(self):
        report = reconcile_model_evidence(self.db, model_code="GL1-336")
        self.assertEqual(len(report["sku_candidates"]), 1)
        self.assertEqual(report["sku_candidates"][0]["sku_id"], self.sku_id)
        self.assertEqual(report["sku_candidates"][0]["mapping_review_status"], "candidate_unconfirmed")
        self.assertEqual(report["models"][0]["confirmed_sku_count"], 0)

    def test_exact_model_source_anchor_rejects_longer_variant(self):
        self.import_pdf("variant.pdf", model="GL1-336A", torque="6 N.m")
        report = reconcile_model_evidence(self.db, model_code="GL1-336")
        self.assertEqual(report["source_mention_count"], 0)
        self.assertEqual(report["source_count"], 0)

    def test_unverified_supplier_assertion_cannot_pass_content_gate(self):
        imported = self.import_pdf(
            "unverified.md.pdf", authority="unverified", kind="supplier_document",
        )
        self.accepted_claim(imported, "6")
        result = evaluate_content_gate(
            self.db, model_code="GL1-336", required_attributes=["Torque"],
        )
        self.assertFalse(result["allowed"])
        self.assertIn("torque", " ".join(result["reasons"]).casefold())

    def test_verified_claim_has_page_hash_and_passes_content_gate(self):
        imported = self.import_pdf()
        self.accepted_claim(imported, "6")
        result = evaluate_content_gate(
            self.db, model_code="GL1-336", required_attributes=["Torque"],
        )
        self.assertTrue(result["allowed"], result["reasons"])
        self.assertEqual(result["approved_claims"][0]["literal_value"], "6")
        evidence = result["approved_claims"][0]["source_evidence"][0]
        self.assertEqual(evidence["source_id"], imported["source_id"])
        self.assertEqual(evidence["pdf_page"], 1)
        self.assertEqual(len(evidence["source_sha256"]), 64)
        self.assertIn("Rated torque", evidence["literal_excerpt"])

    def test_tampered_source_bytes_block_previously_accepted_claim(self):
        imported = self.import_pdf()
        self.accepted_claim(imported, "6")
        stored = self.root / imported["storage_relpath"]
        stored.write_bytes(stored.read_bytes() + b"tampered after review")
        result = evaluate_content_gate(
            self.db, model_code="GL1-336", required_attributes=["Torque"],
        )
        self.assertFalse(result["allowed"])
        report = reconcile_model_evidence(self.db, model_code="GL1-336")
        claim = report["models"][0]["claims"][0]
        self.assertFalse(
            claim["evidence"][0]["source_bytes_verified"],
            repr({"reasons": result["reasons"], "evidence": claim["evidence"][0]}),
        )
        self.assertTrue(
            any("原始文件" in reason for reason in claim["evidence_gate_reasons"]),
            repr({"reasons": result["reasons"], "gate_reasons": claim["evidence_gate_reasons"]}),
        )

    def test_different_accepted_values_create_conflict_and_block_content(self):
        first = self.import_pdf("catalog-a.pdf", torque="6 N.m")
        second = self.import_pdf("catalog-b.pdf", torque="8 N.m")
        self.accepted_claim(first, "6")
        self.accepted_claim(second, "8")
        report = reconcile_model_evidence(self.db, model_code="GL1-336")
        self.assertEqual(len(report["models"][0]["conflicts"]), 1)
        self.assertEqual(report["models"][0]["conflicts"][0]["distinct_value_count"], 2)
        gate = evaluate_content_gate(self.db, model_code="GL1-336", required_attributes=["Torque"])
        self.assertFalse(gate["allowed"])
        self.assertTrue(any("冲突" in reason for reason in gate["reasons"]))

    def test_sku_gate_requires_confirmed_source_backed_mapping(self):
        imported = self.import_pdf()
        self.accepted_claim(imported, "6")
        args = dict(model_code="GL1-336", required_attributes=["Torque"], sku_id=self.sku_id)
        self.assertFalse(evaluate_content_gate(self.db, **args)["allowed"])
        link_id = link_sku_model(
            self.db, sku_id=self.sku_id, model_id=self.model_id, actor="operator",
            note="candidate mapping", source_id=imported["source_id"],
        )
        set_sku_model_link_state(
            self.db, link_id=link_id, state="confirmed", actor="reviewer",
            note="SKU mapping checked against source", source_id=imported["source_id"],
        )
        result = evaluate_content_gate(self.db, **args)
        self.assertTrue(result["allowed"], result["reasons"])

    def test_ambiguous_manufacturer_identity_fails_closed(self):
        add_model(
            self.db, model_code="GL1-336", category="阻尼转轴",
            manufacturer_name="另一家制造商",
        )
        result = evaluate_content_gate(self.db, model_code="GL1-336", required_attributes=["Torque"])
        self.assertFalse(result["allowed"])
        self.assertIn("不唯一", " ".join(result["reasons"]))

    def test_image_rendering_is_blocked_when_bound_copy_differs_from_approved_claim(self):
        imported = self.import_pdf()
        self.accepted_claim(imported, "6")
        source = self.root / "product.png"
        Image.new("RGB", (240, 240), "white").save(source)
        output = self.root / "output.png"
        job = {
            "mode": "main", "source": str(source), "output": str(output),
            "title": "Rated torque 8 N.m",
            "evidence_gate": {
                "database": str(self.db), "model_code": "GL1-336",
                "bindings": [{"field": "title", "attribute": "Torque"}],
            },
        }
        with self.assertRaisesRegex(ValueError, "与已审核参数不一致"):
            build_job(job, self.root)
        self.assertFalse(output.exists())

    def test_image_rendering_records_gate_approval_when_copy_matches(self):
        imported = self.import_pdf()
        self.accepted_claim(imported, "6")
        source = self.root / "product.png"
        Image.new("RGB", (240, 240), "white").save(source)
        output = self.root / "output.png"
        job = {
            "mode": "main", "source": str(source), "output": str(output),
            "title": "Rated torque 6 N.m",
            "evidence_gate": {
                "database": str(self.db), "model_code": "GL1-336",
                "bindings": [{"field": "title", "attribute": "Torque"}],
            },
        }
        result = build_job(job, self.root)
        self.assertTrue(output.is_file())
        self.assertEqual(result["evidence_gate"]["status"], "approved")
        self.assertEqual(result["evidence_gate"]["bindings"][0]["literal_value"], "6")

    def test_sku_spec_binding_requires_label_to_match_claim_attribute(self):
        imported = self.import_pdf()
        self.accepted_claim(imported, "6")
        job = {
            "mode": "sku", "source": "unused.png", "output": "unused-output.png",
            "title": "GL1-336", "specs": [{"label": "材质", "value": "6 N.m"}],
            "evidence_gate": {
                "database": str(self.db), "model_code": "GL1-336",
                "bindings": [{"field": "specs[0].value", "attribute": "Torque"}],
            },
        }
        from ecom_images.image_evidence_gate_v13 import verify_job_evidence_gate
        with self.assertRaisesRegex(ValueError, "规格标签必须"):
            verify_job_evidence_gate(job, self.root)


if __name__ == "__main__":
    unittest.main(verbosity=2)
