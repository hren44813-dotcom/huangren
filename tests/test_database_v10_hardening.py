"""V10 database schema, review semantics and CLI smoke tests."""
from __future__ import annotations
import json, sqlite3, subprocess, sys, tempfile, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
from ecom_images.database_v9 import open_database,save_job,read_job,integrity_report,backup_database,migrate_legacy
from ecom_images.production_ledger_v6 import new_record,record_review,save_record
from ecom_images.sku_review_v5 import FIELDS,review_rows,audit_reviews

class DatabaseV10HardeningTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name); self.db=self.root/"db.sqlite3"
        self.images=[("SKU.jpg",b"synthetic product",{})]
        self.record=new_record(self.images,fingerprint="a"*64,platform="天猫",template="蓝白")

    def test_unversioned_unrelated_database_is_not_claimed(self):
        path=self.root/"other.sqlite3"
        with sqlite3.connect(path) as c: c.execute("CREATE TABLE unrelated(id INTEGER PRIMARY KEY)")
        with self.assertRaisesRegex(RuntimeError,"已有数据库对象"):
            with open_database(path): pass
        with sqlite3.connect(path) as c: self.assertEqual(c.execute("PRAGMA user_version").fetchone()[0],0)

    def test_review_requires_all_checks_and_matching_stage(self):
        save_job(self.db,self.record)
        rows=review_rows(self.images); rows[0].update({k:True for k in FIELDS}); rows[0]["审核结论"]="通过"
        approved=record_review(self.record,self.images,audit_reviews(self.images,rows),reviewer="审核员")
        self.assertEqual(approved["review"]["schema_version"],2)
        forged=json.loads(json.dumps(approved)); forged["review"]["rows"][0]["checks"]["卖点真实性"]=False
        with self.assertRaises(ValueError): save_job(self.db,forged,expected_revision=1)
        with self.assertRaisesRegex(ValueError,"阶段与审核统计不一致"):
            save_job(self.db,{**approved,"stage":"待人工审核"},expected_revision=1)

    def test_approval_cannot_be_inserted_with_new_job(self):
        rows=review_rows(self.images); rows[0].update({k:True for k in FIELDS}); rows[0]["审核结论"]="通过"
        approved=record_review(self.record,self.images,audit_reviews(self.images,rows),reviewer="审核员")
        with self.assertRaisesRegex(ValueError,"先以待审核状态创建"): save_job(self.db,approved)

    def test_integrity_detects_denormalized_job_drift(self):
        save_job(self.db,self.record)
        with open_database(self.db) as c: c.execute("UPDATE jobs SET platform='伪造平台' WHERE id=?",(self.record["id"],))
        report=integrity_report(self.db)
        self.assertFalse(report["ok"]); self.assertTrue(any("冗余字段" in x for x in report["logical_errors"]))

    def test_casefold_filename_collision_rejected(self):
        record=new_record([("SKU.jpg",b"a",{}),("sku.JPG",b"b",{})],fingerprint="b"*64,platform="天猫",template="蓝白")
        with self.assertRaisesRegex(ValueError,"忽略大小写"): save_job(self.db,record)

    def test_review_triggers_prevent_updates_and_check_detects_dropped_guard(self):
        save_job(self.db,self.record)
        with open_database(self.db) as c:
            c.execute("INSERT INTO review_events(job_id,created_utc,reviewer,report_sha256,review_json) VALUES(?,?,?,?,?)",
                (self.record["id"],"2026-10-27T00:00:00+00:00","测试审核员","0"*64,"{}"))
            with self.assertRaises(sqlite3.IntegrityError): c.execute("UPDATE review_events SET reviewer='fake'")
            with self.assertRaises(sqlite3.IntegrityError): c.execute("DELETE FROM review_events")
            c.execute("DROP TRIGGER review_events_no_update")
        report=integrity_report(self.db)
        self.assertFalse(report["ok"]); self.assertTrue(any("触发器" in x for x in report["logical_errors"]))

    def test_legacy_review_import_requires_rereview(self):
        old=new_record(self.images,fingerprint="c"*64,platform="天猫",template="蓝白")
        rows=review_rows(self.images); rows[0].update({k:True for k in FIELDS}); rows[0]["审核结论"]="通过"
        old=record_review(old,self.images,audit_reviews(self.images,rows),reviewer="旧版审核员")
        old["review"].pop("schema_version")
        for row in old["review"]["rows"]: row.pop("checks",None)
        source=self.root/"legacy"; source.mkdir(); save_record(source,old)
        result=migrate_legacy(self.db,job_directory=source,template_directory=self.root/"no-templates")
        self.assertEqual(result["jobs_imported"],1)
        loaded,_=read_job(self.db,old["id"])
        self.assertFalse(loaded["review"]["ready_to_publish"]); self.assertEqual(loaded["stage"],"历史审核需复核")
        self.assertTrue(integrity_report(self.db)["ok"])

    def test_v1_backup_migrates_snapshot_not_source(self):
        save_job(self.db,self.record)
        with open_database(self.db) as c:
            c.execute("DROP TRIGGER review_events_no_update"); c.execute("DROP TRIGGER review_events_no_delete")
            c.execute("PRAGMA user_version=1")
        self.assertEqual(integrity_report(self.db)["schema_version"],1)
        backup=self.root/"backup.sqlite3"; backup_database(self.db,backup)
        with sqlite3.connect(self.db) as c: self.assertEqual(c.execute("PRAGMA user_version").fetchone()[0],1)
        with sqlite3.connect(backup) as c: self.assertEqual(c.execute("PRAGMA user_version").fetchone()[0],2)

    def test_health_check_missing_path_is_read_only(self):
        path=self.root/"missing.sqlite3"; self.assertFalse(integrity_report(path)["ok"]); self.assertFalse(path.exists())

    def test_dry_run_does_not_migrate_existing_v1_database(self):
        save_job(self.db, self.record)
        with open_database(self.db) as conn:
            conn.execute("DROP TRIGGER review_events_no_update")
            conn.execute("DROP TRIGGER review_events_no_delete")
            conn.execute("PRAGMA user_version=1")
        jobs = self.root / "legacy_jobs"
        templates = self.root / "legacy_templates"
        jobs.mkdir(); templates.mkdir()
        old = new_record([("OLD.jpg", b"legacy", {})], fingerprint="d"*64, platform="天猫", template="蓝白")
        save_record(jobs, old)
        result = migrate_legacy(self.db, job_directory=jobs, template_directory=templates, dry_run=True)
        self.assertEqual(result["would_import"], 1)
        with sqlite3.connect(self.db) as conn:
            self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT count(*) FROM jobs").fetchone()[0], 1)

class DatabaseV10CliTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name); self.db=self.root/"records.sqlite3"
    def cli(self,*args):
        return subprocess.run([sys.executable,str(ROOT/"scripts/db_admin.py"),"--database",str(self.db),*args],
            cwd=ROOT,text=True,capture_output=True,timeout=20)
    def test_cli_init_check_backup_restore(self):
        self.assertEqual(self.cli("init").returncode,0)
        checked=self.cli("check"); self.assertEqual(checked.returncode,0,checked.stdout+checked.stderr)
        self.assertTrue(json.loads(checked.stdout)["ok"])
        backup=self.root/"backup.sqlite3"; self.assertEqual(self.cli("backup","--output",str(backup)).returncode,0)
        restored=self.cli("restore","--source",str(backup),"--overwrite","--app-stopped")
        self.assertEqual(restored.returncode,0,restored.stdout+restored.stderr)
        self.assertEqual(self.cli("check").returncode,0)
    def test_cli_check_missing_database_is_read_only(self):
        result=self.cli("check"); self.assertEqual(result.returncode,1); self.assertFalse(self.db.exists())
    def test_cli_dry_run_does_not_create_database(self):
        jobs=self.root/"jobs"; templates=self.root/"templates"; jobs.mkdir(); templates.mkdir()
        result=self.cli("import-legacy","--jobs",str(jobs),"--templates",str(templates),"--dry-run")
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertFalse(self.db.exists()); self.assertTrue(json.loads(result.stdout)["dry_run"])

if __name__=="__main__": unittest.main()
