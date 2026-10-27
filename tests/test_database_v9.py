"""SQLite V9 regression checks: migration, collision, audit history, backup/restore."""
from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from ecom_images.database_v9 import (
    backup_database, delete_template, integrity_report, list_jobs, list_templates,
    load_template, migrate_legacy, open_database, read_job, restore_database,
    review_history, save_job, save_template,
)
from ecom_images.production_ledger_v6 import new_record, record_review, save_record
from ecom_images.sku_layout_v4 import default_layout, layout_json
from ecom_images.sku_review_v5 import FIELDS, audit_reviews, review_rows


class DatabaseV9Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.db = self.root / "local" / "records.sqlite3"
        self.images = [("SKU_LS200.jpg", b"realistic-synthetic-image", {})]
        self.record = new_record(self.images, fingerprint="f"*64,
                                 platform="淘宝/天猫", template="蓝白工业参数风")

    def test_initialize_and_round_trip(self):
        self.assertEqual(save_job(self.db, self.record), 1)
        obj, rev = read_job(self.db, self.record["id"])
        self.assertEqual((obj, rev), (self.record, 1))
        self.assertEqual(list_jobs(self.db)[0]["阶段"], "待人工审核")
        self.assertEqual(integrity_report(self.db)["counts"]["job_files"], 1)
        self.assertEqual(save_job(self.db, self.record, expected_revision=1), 1)

    def test_two_tabs_cannot_overwrite_approvals(self):
        save_job(self.db, self.record)
        rows = review_rows(self.images)
        rows[0].update({name: True for name in FIELDS})
        rows[0]["审核结论"] = "通过"
        report = audit_reviews(self.images, rows)
        approved = record_review(self.record, self.images, report, reviewer="运营A")
        self.assertEqual(save_job(self.db, approved, expected_revision=1), 2)
        self.assertEqual(len(review_history(self.db, self.record["id"])), 1)
        with self.assertRaisesRegex(ValueError, "窗口更新"):
            save_job(self.db, approved, expected_revision=1)
        self.assertEqual(save_job(self.db, approved, expected_revision=2), 2)
        report["rows"][0]["note"] = "复核材质"
        # record_review already checks report signature against actual image bytes
        renewed_report = audit_reviews(self.images, rows)
        renewed_report["rows"][0]["note"] = "extra"  # signature validation needed at reviewer stage, not DB stage
        amended = record_review(approved, self.images, audit_reviews(self.images, rows), reviewer="运营B")
        self.assertEqual(save_job(self.db, amended, expected_revision=2), 3)
        self.assertEqual(len(review_history(self.db, self.record["id"])), 2)
        self.assertTrue(integrity_report(self.db)["ok"])

    def test_core_data_cannot_change_or_insert_duplicate(self):
        save_job(self.db, self.record)
        forged = {**self.record, "input_sha256": "a" * 64}
        with self.assertRaisesRegex(ValueError, "核心数据"):
            save_job(self.db, forged, expected_revision=1)
        with self.assertRaisesRegex(ValueError, "窗口更新"):
            save_job(self.db, self.record)
        self.assertEqual(read_job(self.db, self.record["id"])[0], self.record)

    def test_bad_records_are_not_partially_persisted(self):
        bad = {**self.record, "generated": 999}
        with self.assertRaisesRegex(ValueError, "生成数量"):
            save_job(self.db, bad)
        self.assertIsNone(read_job(self.db, self.record["id"]))

    def test_template_casefold_and_hash(self):
        layout = default_layout("蓝白工业参数风")
        self.assertEqual(save_template(self.db, "Handle_A", layout), "Handle_A")
        self.assertEqual(load_template(self.db, "HANDLE_a"), layout)
        with self.assertRaisesRegex(ValueError, "已存在"):
            save_template(self.db, "handle_a", layout)
        self.assertEqual(save_template(self.db, "HANDLE_A", layout, overwrite=True), "Handle_A")
        self.assertEqual(list_templates(self.db), ["Handle_A"])
        delete_template(self.db, "handle_a")
        self.assertEqual(list_templates(self.db), [])

    def test_invalid_layout_rolls_back(self):
        layout = default_layout("蓝白工业参数风")
        save_template(self.db, "规范模板", layout)
        with self.assertRaises(ValueError):
            save_template(self.db, "规范模板", {"slots": {}}, overwrite=True)
        self.assertEqual(load_template(self.db, "规范模板"), layout)

    def test_legacy_migration_and_repeat_does_not_delete_json(self):
        jobs = self.root / "legacy_jobs"
        templates = self.root / "legacy_templates"
        jobs.mkdir()
        templates.mkdir()
        save_record(jobs, self.record)
        (templates / "拉手蓝白.json").write_bytes(layout_json(default_layout("蓝白工业参数风")))
        result = migrate_legacy(self.db, job_directory=jobs, template_directory=templates)
        self.assertEqual((result["jobs_imported"], result["templates_imported"], result["errors"]), (1, 1, []))
        self.assertTrue((jobs / (self.record["id"] + ".json")).is_file())
        second = migrate_legacy(self.db, job_directory=jobs, template_directory=templates)
        self.assertEqual((second["unchanged"],second["errors"]), (2, []))
        self.assertEqual(integrity_report(self.db)["counts"]["jobs"], 1)
        self.assertEqual(list_templates(self.db), ["拉手蓝白"])

    def test_legacy_corrupt_and_modified_conflict(self):
        jobs = self.root / "jobs"
        templates = self.root / "templates"
        jobs.mkdir(); templates.mkdir()
        save_record(jobs, self.record)
        (jobs / "broken.json").write_text("{oops", encoding="utf-8")
        output = migrate_legacy(self.db, job_directory=jobs, template_directory=templates)
        self.assertEqual(output["jobs_imported"], 1)
        self.assertEqual(len(output["errors"]), 1)
        file = jobs / (self.record["id"] + ".json")
        file.write_text(file.read_text(encoding="utf-8") + " ", encoding="utf-8")
        again = migrate_legacy(self.db, job_directory=jobs, template_directory=templates)
        self.assertTrue(any("已改变" in e for e in again["errors"]))
        self.assertEqual(integrity_report(self.db)["counts"]["jobs"], 1)

    def test_concurrent_snapshot_backup_and_restore(self):
        save_job(self.db, self.record)
        save_template(self.db, "尺寸模板", default_layout("灰白极简技术风"))
        backup = self.root / "safe.sqlite3"
        self.assertEqual(backup_database(self.db, backup), backup)
        with self.assertRaisesRegex(ValueError, "已存在"):
            backup_database(self.db, backup)
        with open_database(self.db) as con:
            con.execute("DELETE FROM templates")
        self.assertEqual(list_templates(self.db), [])
        # Must close the Streamlit process / all DB connections to restore.
        restored = restore_database(backup, self.db, overwrite=True)
        self.assertEqual(restored, self.db)
        self.assertEqual(list_templates(self.db), ["尺寸模板"])
        self.assertEqual(read_job(self.db, self.record["id"])[0], self.record)
        self.assertTrue(integrity_report(self.db)["ok"])

    def test_integrity_detects_wrong_sha(self):
        save_job(self.db, self.record)
        with open_database(self.db) as conn:
            conn.execute("UPDATE job_files SET sha256=?", ("1"*64,))
        status = integrity_report(self.db)
        self.assertFalse(status["ok"])
        self.assertTrue(status["logical_errors"])

    def test_sqlite_fk_and_future_schema_rejected(self):
        with open_database(self.db) as conn:
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute("INSERT INTO job_files(job_id,name,sha256) VALUES('no-such-job','x.png',?)", ("f"*64,))
            conn.execute("PRAGMA user_version=99")
        with self.assertRaisesRegex(RuntimeError, "高于"):
            read_job(self.db, self.record["id"])

    def test_no_embedded_photo_or_api_key(self):
        save_job(self.db, self.record)
        raw = self.db.read_bytes()
        self.assertNotIn(b"realistic-synthetic-image", raw)
        self.assertNotIn(b"OPENAI_IMAGE_API_KEY", raw)
        self.assertTrue(integrity_report(self.db)["ok"])

    def test_integrity_check_missing_path_is_read_only(self):
        missing = self.root / "does-not-exist" / "missing.sqlite3"
        result = integrity_report(missing)
        self.assertFalse(result["ok"])
        self.assertFalse(missing.exists())
        self.assertIn("未创建新文件", result["logical_errors"][0])

    def test_legacy_dry_run_does_not_create_target_database(self):
        missing = self.root / "dryrun" / "records.sqlite3"
        jobs = self.root / "dry_jobs"
        templates = self.root / "dry_templates"
        jobs.mkdir(); templates.mkdir()
        save_record(jobs, self.record)
        result = migrate_legacy(missing, job_directory=jobs, template_directory=templates, dry_run=True)
        self.assertEqual(result["would_import"], 1)
        self.assertEqual(result["jobs_imported"], 0)
        self.assertFalse(missing.exists())
        self.assertTrue((jobs / f"{self.record['id']}.json").exists())

    def test_backup_missing_database_refuses_to_create_blank_backup(self):
        missing = self.root / "missing.sqlite3"
        backup = self.root / "backup.sqlite3"
        with self.assertRaisesRegex(ValueError, "源数据库不存在"):
            backup_database(missing, backup)
        self.assertFalse(missing.exists())
        self.assertFalse(backup.exists())

    def test_integrity_detects_tampered_review_event(self):
        save_job(self.db, self.record)
        rows = review_rows(self.images)
        rows[0].update({name: True for name in FIELDS})
        rows[0]["审核结论"] = "通过"
        report = audit_reviews(self.images, rows)
        reviewed = record_review(self.record, self.images, report, reviewer="运营A")
        save_job(self.db, reviewed, expected_revision=1)
        with open_database(self.db) as conn:
            conn.execute("DROP TRIGGER review_events_no_update")
            conn.execute("UPDATE review_events SET review_json=?", ('{"reviewer":"伪造"}',))
        status = integrity_report(self.db)
        self.assertFalse(status["ok"])
        self.assertTrue(any("审核事件" in item for item in status["logical_errors"]))

    def test_legacy_template_migration_obeys_template_limit(self):
        templates = self.root / "legacy_templates"
        templates.mkdir()
        layout = default_layout("蓝白工业参数风")
        for i in range(80):
            save_template(self.db, f"模板{i:02d}", layout)
        (templates / "第81套.json").write_bytes(layout_json(layout))
        result = migrate_legacy(self.db, job_directory=self.root / "no-jobs", template_directory=templates)
        self.assertEqual(result["templates_imported"], 0)
        self.assertTrue(any("最多保存" in err for err in result["errors"]))
        self.assertEqual(len(list_templates(self.db)), 80)


if __name__ == "__main__":
    unittest.main()

# Additional security and operational regressions are kept in a separate class
# so they are discovered by unittest on Python 3.10 and Python 3.12.
class OperationalDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.addCleanup(self.td.cleanup)
        self.root = Path(self.td.name)
        self.db = self.root / "data.sqlite3"

    def test_dry_run_leaves_original_json_unmodified(self):
        items = [("SKU_a.jpg", b"x", {})]
        record = new_record(items, fingerprint="a" * 64, platform="天猫", template="测试")
        folder = self.root / "legacy"
        save_record(folder, record)
        out = migrate_legacy(self.db, job_directory=folder,
                             template_directory=self.root / "no-templates", dry_run=True)
        self.assertEqual(out["would_import"], 1)
        self.assertEqual(out["jobs_imported"], 0)
        self.assertEqual(integrity_report(self.db)["counts"]["jobs"], 0)
        self.assertTrue((folder / (record["id"] + ".json")).exists())

    def test_database_refuses_unrecognized_sensitive_fields(self):
        record = new_record([], fingerprint="a"*64, platform="天猫", template="蓝白")
        record["OPENAI_IMAGE_API_KEY"] = "THIS_IS_A_SECRET"
        with self.assertRaisesRegex(ValueError, "未知字段"):
            save_job(self.db, record)

    def test_tampered_review_event_fails_business_integrity(self):
        files = [("SKU_a.jpg", b"x", {})]
        record = new_record(files, fingerprint="a"*64, platform="天猫", template="蓝白")
        save_job(self.db, record)
        rows = review_rows(files)
        rows[0].update({key: True for key in FIELDS})
        rows[0]["审核结论"] = "通过"
        approved = record_review(record, files, audit_reviews(files, rows), reviewer="审核员")
        save_job(self.db, approved, expected_revision=1)
        with open_database(self.db) as conn:
            conn.execute("DROP TRIGGER review_events_no_update")
            conn.execute("UPDATE review_events SET report_sha256=?", ("0"*64,))
        self.assertFalse(integrity_report(self.db)["ok"])
        with self.assertRaisesRegex(ValueError, "完整性"):
            backup_database(self.db, self.root / "bad-copy.sqlite3")

    def test_backup_non_destructive_on_corrupt_source(self):
        record = new_record([], fingerprint="a"*64, platform="天猫", template="蓝白")
        save_job(self.db, record)
        destination = self.root / "preexisting.db"
        destination.write_bytes(b"keep me")
        with self.assertRaises(ValueError):
            backup_database(self.db, destination)
        self.assertEqual(destination.read_bytes(), b"keep me")
        with open_database(self.db) as conn:
            conn.execute("UPDATE jobs SET record_json='not-json'")
        with self.assertRaisesRegex(ValueError, "完整性"):
            backup_database(self.db, self.root / "broken.sqlite3")
        self.assertFalse((self.root / "broken.sqlite3").exists())

    def test_restore_requires_explicit_overwrite(self):
        record = new_record([], fingerprint="a"*64, platform="天猫", template="蓝白")
        save_job(self.db, record)
        safe = self.root / "copy.sqlite3"
        backup_database(self.db, safe)
        with self.assertRaises(ValueError):
            restore_database(safe, self.db)
        self.assertEqual(read_job(self.db, record["id"])[0], record)
