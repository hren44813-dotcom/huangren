"""V11 reporting: pagination, safe export, no mutation, query isolation."""
from __future__ import annotations
import hashlib
import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from ecom_images.db_reporting_v11 import (database_summary, job_review_timeline,
                                         jobs_csv, list_job_page)


class ReportingTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.db = self.root / "records.sqlite3"
        with sqlite3.connect(self.db) as conn:
            conn.executescript("""
            CREATE TABLE jobs(id TEXT PRIMARY KEY, created_utc TEXT, updated_utc TEXT,
             platform TEXT,template TEXT,input_sha256 TEXT,generated INTEGER,
             failed_generation INTEGER,stage TEXT,record_json TEXT,revision INTEGER);
            CREATE TABLE job_files(job_id TEXT,name TEXT,sha256 TEXT);
            CREATE TABLE review_events(event_id INTEGER PRIMARY KEY AUTOINCREMENT,
             job_id TEXT,created_utc TEXT,reviewer TEXT,report_sha256 TEXT,review_json TEXT);
            CREATE TABLE templates(name_key TEXT,name TEXT,layout_json TEXT,layout_sha256 TEXT);
            CREATE TABLE imported_files(origin TEXT,kind TEXT,sha256 TEXT);
            PRAGMA user_version=2;
            """)
            for i,day in enumerate(("2026-10-01", "2026-10-02", "2026-10-02", "2026-10-03")):
                ident = f"{i + 1:032x}"
                conn.execute("""INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                             (ident, day+"T10:20:00+00:00", day+"T11:00:00+00:00",
                              "天猫" if i != 2 else "阿里国际站", "锁具_主图" if i!=3 else "=CSV风险",
                              "a"*64, i+1, 0, "待人工审核" if i!=2 else "返工中", "{}", 1))
            first = f"{1:032x}"
            report = json.dumps({"test": "review"}, ensure_ascii=False)
            digest = hashlib.sha256(report.encode()).hexdigest()
            conn.execute("INSERT INTO review_events(job_id,created_utc,reviewer,report_sha256,review_json) VALUES(?,?,?,?,?)",
                         (first,"2026-10-03T01:00:00+00:00","审核人",digest,report))
            conn.commit()
        self.first = f"{1:032x}"

    def test_summary_and_rows(self):
        s = database_summary(self.db)
        self.assertEqual(s["totals"]["jobs"],4)
        self.assertEqual(s["totals"]["review_events"],1)
        self.assertEqual(s["orphan_job_files"],0)
        self.assertEqual(sum(x["count"] for x in s["by_stage"]),4)

    def test_stable_pages(self):
        p1 = list_job_page(self.db,page_size=2,page=1)
        p2 = list_job_page(self.db,page_size=2,page=2)
        self.assertEqual(p1["total"],4)
        self.assertEqual(len(p1["rows"]),2)
        self.assertFalse({r["id"] for r in p1["rows"]} & {r["id"] for r in p2["rows"]})
        self.assertEqual(list_job_page(self.db,page=5)["rows"],[])

    def test_stage_platform_date_filter(self):
        self.assertEqual(list_job_page(self.db,stage="返工中")["total"],1)
        self.assertEqual(list_job_page(self.db,platform="阿里国际站")["total"],1)
        self.assertEqual(list_job_page(self.db,since="2026-10-02",until="2026-10-02")["total"],2)
        self.assertEqual(list_job_page(self.db,keyword="主图")["total"],3)
        self.assertEqual(list_job_page(self.db,keyword="9999")["total"],0)
        self.assertEqual(list_job_page(self.db,keyword="' OR 1=1 --")["total"],0)
        self.assertEqual(list_job_page(self.db,keyword="_%")["total"],0)

    def test_reject_invalid_filters(self):
        for kwargs in ({"page":0},{"page_size":101},{"page":True},
                       {"since":"2026-02-30"}, {"since":"2026-10-05","until":"2026-10-04"},
                       {"keyword":""}, {"since":"2026/10/01"}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                list_job_page(self.db,**kwargs)

    def test_csv_injection_escaped(self):
        csv = jobs_csv(list_job_page(self.db,page_size=4))
        self.assertTrue(csv.startswith("\ufeff"))
        self.assertIn("'=CSV风险",csv)
        with self.assertRaises(ValueError): jobs_csv({"rows":[{}]*101})

    def test_review_checksum_and_mismatched_digest(self):
        good = job_review_timeline(self.db,self.first)
        self.assertEqual(good["job"]["generated"],1)
        self.assertTrue(good["events"][0]["checksum_ok"])
        with sqlite3.connect(self.db) as conn:
            conn.execute("UPDATE review_events SET review_json='{}'")
        bad = job_review_timeline(self.db,self.first)
        self.assertFalse(bad["events"][0]["checksum_ok"])
        with self.assertRaises(ValueError): job_review_timeline(self.db,"1")

    def test_missing_path_or_bad_schema_no_writes(self):
        missing = self.root/"absent.sqlite3"
        with self.assertRaisesRegex(ValueError,"不存在"):
            database_summary(missing)
        self.assertFalse(missing.exists())
        with sqlite3.connect(self.db) as conn:
            conn.execute("PRAGMA user_version=99")
        with self.assertRaisesRegex(ValueError,"不支持"):
            database_summary(self.db)

    def test_symlink_rejected(self):
        link = self.root / "link.sqlite3"
        link.symlink_to(self.db)
        with self.assertRaisesRegex(ValueError,"符号链接"):
            database_summary(link)

    def test_cli_json_csv_and_errors(self):
        script = ROOT/"scripts/db_report.py"
        common = [sys.executable,str(script),"--database",str(self.db)]
        s = subprocess.run(common+["summary"],capture_output=True,text=True,timeout=10)
        self.assertEqual(s.returncode,0,s.stderr)
        self.assertEqual(json.loads(s.stdout)["totals"]["jobs"],4)
        c = subprocess.run(common+["jobs","--format","csv"],capture_output=True,text=True,timeout=10)
        self.assertEqual(c.returncode,0,c.stderr)
        self.assertIn("'=CSV风险",c.stdout)
        e = subprocess.run(common+["reviews","not-an-id"],capture_output=True,text=True,timeout=10)
        self.assertNotEqual(e.returncode,0)

if __name__ == "__main__": unittest.main()