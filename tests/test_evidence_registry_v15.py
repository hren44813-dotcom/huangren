import copy,json,sqlite3,sys,unittest,hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/"src"))
from ecom_images.evidence_registry_v15 import audit,contains_exact_model,verify_source_bytes,export_claims_csv,export_status_csv,init_db,import_db,check_db
class Tests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.h=json.loads((ROOT/"assets/history/history_reference_v13.json").read_text(encoding="utf-8"));cls.s=json.loads((ROOT/"assets/history/evidence_seed_v15.json").read_text(encoding="utf-8"))
 def test_counts(self):
  r=audit(self.h,self.s);self.assertEqual(r["history_records"],74);self.assertEqual(r["claims_count"],87);self.assertEqual(r["records_with_exact_model_listed"],35);self.assertEqual(r["records_with_any_source_anchor"],42);self.assertEqual(r["independent_engineering_verifications"],0)
 def test_exact_boundaries(self):
  self.assertFalse(contains_exact_model("GL1-103-50","103"));self.assertFalse(contains_exact_model("MS705-Z","MS705"));self.assertFalse(contains_exact_model("HC-XAH18","XAH18"));self.assertTrue(contains_exact_model("MS705-Z","MS705-Z"))
 def test_wrong_exact_value_rejected(self):
  s=copy.deepcopy(self.s);c=next(c for c in s["claims"] if c["claim_type"]=="exact_model_listed" and c["history_model"]=="MS705-Z");c["value"]="MS705"
  with self.assertRaises(ValueError):audit(self.h,s)
 def test_variant_not_exact(self):
  s=copy.deepcopy(self.s);c=next(c for c in s["claims"] if c["claim_type"]=="family_variant_listed");c["value"]=c["history_model"]
  with self.assertRaises(ValueError):audit(self.h,s)
 def test_alias_unconfirmed(self):
  c=next(c for c in self.s["claims"] if c["claim_type"]=="candidate_alias");self.assertEqual(c["value"],"HC-XAH18");self.assertEqual(c["review_status"],"candidate_unconfirmed")
 def test_bad_source_hash(self):
  s=copy.deepcopy(self.s);s["sources"][0]["sha256"]="bad"
  with self.assertRaises(ValueError):audit(self.h,s)
 def test_bad_page(self):
  s=copy.deepcopy(self.s);s["claims"][0]["pdf_page"]=196
  with self.assertRaises(ValueError):audit(self.h,s)
 def test_duplicate_claim_id(self):
  s=copy.deepcopy(self.s);s["claims"][1]["claim_id"]=s["claims"][0]["claim_id"]
  with self.assertRaises(ValueError):audit(self.h,s)
 def test_no_fake_engineering_claim(self):
  s=copy.deepcopy(self.s);s["claims"][0]["claim_type"]="material"
  with self.assertRaises(ValueError):audit(self.h,s)
 def test_source_bytes(self):
  raw=b"source";out=verify_source_bytes(raw,{"sha256":hashlib.sha256(raw).hexdigest(),"size_bytes":len(raw)});self.assertTrue(out["sha256_matches"]);self.assertTrue(out["size_matches"])
 def test_csv_outputs(self):
  r=audit(self.h,self.s);self.assertTrue(export_claims_csv(r).startswith(b"\xef\xbb\xbf"));self.assertEqual(len(export_status_csv(r).decode("utf-8-sig").splitlines()),75)
 def test_sqlite_dry_run_and_idempotence(self):
  c=sqlite3.connect(":memory:");c.execute("PRAGMA foreign_keys=ON");c.execute("CREATE TABLE catalog_skus(id TEXT PRIMARY KEY,model TEXT)");c.execute("INSERT INTO catalog_skus VALUES('sku','untouched')");c.commit();init_db(c)
  self.assertEqual(import_db(c,self.h,self.s,True)["claims_added"],87);self.assertEqual(c.execute("SELECT count(*) FROM evidence_v15_claims").fetchone()[0],0)
  a=import_db(c,self.h,self.s);self.assertEqual(a["history_added"],74);self.assertEqual(a["claims_added"],87);b=import_db(c,self.h,self.s);self.assertEqual(b["claims_added"],0);self.assertEqual(b["unchanged"],88);self.assertTrue(check_db(c)["ok"]);self.assertEqual(c.execute("SELECT model FROM catalog_skus").fetchone()[0],"untouched")
 def test_sqlite_conflict_rolls_back(self):
  c=sqlite3.connect(":memory:");c.execute("PRAGMA foreign_keys=ON");init_db(c);import_db(c,self.h,self.s);s=copy.deepcopy(self.s);s["claims"][0]["notes"]="tamper"
  with self.assertRaises(ValueError):import_db(c,self.h,s)
  self.assertEqual(check_db(c)["claims"],87)
 def test_sqlite_append_only(self):
  c=sqlite3.connect(":memory:");c.execute("PRAGMA foreign_keys=ON");init_db(c);import_db(c,self.h,self.s)
  with self.assertRaises(sqlite3.IntegrityError):c.execute("DELETE FROM evidence_v15_claims WHERE claim_id=?",(self.s["claims"][0]["claim_id"],))
  with self.assertRaises(sqlite3.IntegrityError):c.execute("UPDATE evidence_v15_sources SET title='tamper'")
if __name__=="__main__":unittest.main()
