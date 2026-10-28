from __future__ import annotations
import copy,json,sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/"src"))
from ecom_images.gl1_336_deep_audit_v16 import validate_evidence, exact_model_occurrences, extract_code_forms
class GL1336DeepAuditV16Tests(unittest.TestCase):
 @classmethod
 def setUpClass(cls): cls.e=json.loads((ROOT/"assets/gl1_336_deep_evidence_v16.json").read_text(encoding="utf-8"))
 def test_baseline_registry_passes(self):
  r=validate_evidence(self.e);self.assertTrue(r["ok"],r["errors"]);self.assertEqual(r["target_model"],"GL1-336");self.assertEqual(r["claims"],27)
 def test_single_model_scope(self): self.assertEqual(self.e["target"]["model"],"GL1-336");self.assertIn("no expansion of model count",self.e["task"].lower())
 def test_source_fingerprint(self):
  s=self.e["source"]["source_integrity"];self.assertRegex(s["sha256"],r"^[0-9a-f]{64}$");self.assertEqual(s["size_bytes"],173132513);self.assertEqual(s["pdf_pages"],195)
 def test_precise_page_locator(self): self.assertEqual(self.e["source"]["page_locator"]["pdf_page_1based"],37);self.assertEqual(self.e["source"]["page_locator"]["printed_page_visible"],"24")
 def test_original_not_publicly_bundled(self): self.assertEqual(self.e["source"]["privacy"],"source_pdf_and_crops_not_committed_to_public_repository")
 def test_catalog_identity_not_physical_identity(self):
  m=self.e["verification_matrix"];self.assertEqual(m["model_label_present_in_catalog"],"confirmed_from_page_only");self.assertEqual(m["physical_product_identity"],"not_verified")
 def test_torque_unit_conflict_open(self):
  c={x["conflict_id"]:x for x in self.e["conflicts"]}["CON-001"];self.assertEqual(c["status"],"OPEN");self.assertIn("kgf·cm",c["evidence_a"]["literal"]);self.assertIn("N.m",c["evidence_b"]["literal"])
 def test_letter_o_zero_conflict_open(self):
  c=next(x for x in self.e["conflicts"] if x["conflict_id"]=="CON-002");self.assertEqual(c["status"],"OPEN");self.assertIn("HCO1-03600",c["evidence_a"]["literal_forms"])
 def test_geometry_semantics_not_inferred(self):
  c=next(x for x in self.e["conflicts"] if x["conflict_id"]=="CON-003");self.assertEqual(c["status"],"OPEN");d=next(x for x in self.e["claims"] if x["claim_id"]=="DIM-004");self.assertIn("native CAD",d["limitations"])
 def test_revision_currency_unknown(self): self.assertEqual(self.e["source"]["revision_date_status"],"unknown_not_found_in_metadata_or_text_search");self.assertEqual(self.e["verification_matrix"]["current_controlled_revision"],"unknown")
 def test_twelve_part_code_rows_not_shop_skus(self): self.assertEqual(len(self.e["catalog_variant_rows"]),12);self.assertTrue(all(x["history_sku_binding"] is None for x in self.e["catalog_variant_rows"]))
 def test_each_finish_has_torque_options_one_to_six(self):
  for finish in ("镀镍","镀锌镍"): self.assertEqual([x["torque_catalog_value"] for x in self.e["catalog_variant_rows"] if x["surface_finish_catalog"]==finish],[1,2,3,4,5,6])
 def test_part_code_prefix_not_canonicalized_as_verified(self):
  rows=self.e["catalog_variant_rows"];self.assertTrue(all(x["code_status"]=="needs_second_person_and_BOM_confirmation" for x in rows));self.assertTrue(any(x["pdf_text_layer_code"].startswith("HCO1-") for x in rows))
 def test_no_claim_overstates_independent_verification(self):
  for c in self.e["claims"]: self.assertNotIn(c["status"],{"independently_verified","engineering_verified","physically_verified"});self.assertIsNone(c["independent_reviewer"])
  self.assertEqual(self.e["verification_matrix"]["independent_engineer_review"],"not_performed")
 def test_unique_claims_all_scoped_to_page_37(self):
  c=self.e["claims"];self.assertEqual(len({x["claim_id"] for x in c}),len(c));self.assertTrue(all(x["pdf_page_1based"]==37 for x in c))
 def test_metadata_unknown_not_guessed(self):
  m=self.e["source"]["pdf_metadata"];self.assertEqual(m["title"],"");self.assertEqual(m["creationDate"],"");self.assertEqual(m["modDate"],"")
 def test_tampered_hash_rejected(self):
  e=copy.deepcopy(self.e);e["source"]["source_integrity"]["sha256"]="bad";r=validate_evidence(e);self.assertFalse(r["ok"]);self.assertTrue(any("SHA-256" in x for x in r["errors"]))
 def test_conflict_cannot_be_closed_without_evidence(self):
  e=copy.deepcopy(self.e);next(x for x in e["conflicts"] if x["conflict_id"]=="CON-001")["status"]="RESOLVED";r=validate_evidence(e);self.assertFalse(r["ok"]);self.assertTrue(any("CON-001" in x for x in r["errors"]))
if __name__=="__main__": unittest.main(verbosity=2)
