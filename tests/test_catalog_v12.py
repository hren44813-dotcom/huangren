"""Regression and migration safety tests for the V12 commerce catalog."""
import csv
import hashlib
import io
import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from ecom_images.catalog_v12 import (  # noqa: E402
    COLUMNS, attach_asset, catalog_audit, catalog_summary, csv_template, import_catalog_csv,
    initialize_catalog, link_job_sku, list_skus,
)
from ecom_images.database_v9 import open_database  # noqa: E402
from ecom_images.production_ledger_v6 import new_record  # noqa: E402
from ecom_images.database_v9 import save_job  # noqa: E402


def rows_bytes(*items):
    buf=io.StringIO(newline="")
    writer=csv.DictWriter(buf, fieldnames=COLUMNS)
    writer.writeheader()
    for item in items: writer.writerow(item)
    return ("\ufeff"+buf.getvalue()).encode("utf-8")


def sample(**overrides):
    value={"店铺编码":"SHOP-1","店铺名称":"工业五金旗舰店","平台":"天猫",
           "商品编码":"GL-300","商品名称":"工业设备拉手","商品类别":"工业拉手",
           "SKU编码":"GL-300-200","产品型号":"GL-300","材质":"304不锈钢",
           "表面处理":"拉丝","孔距(mm)":"200","总长(mm)":"228","备注":""}
    value.update(overrides)
    return value


class CatalogV12Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.db=self.root/"huangren.sqlite3"

    def test_initialize_creates_related_tables_without_erasing_jobs(self):
        record=new_record([("SKU.jpg",b"fake",{})],fingerprint="a"*64,platform="天猫",template="蓝白")
        save_job(self.db,record)
        with open_database(self.db) as con:
            base_version = con.execute("PRAGMA user_version").fetchone()[0]
        initialize_catalog(self.db)
        initialize_catalog(self.db)
        self.assertEqual(catalog_summary(self.db)["counts"]["stores"],0)
        with open_database(self.db) as con:
            self.assertEqual(con.execute("SELECT count(*) FROM jobs").fetchone()[0],1)
            self.assertEqual(con.execute("PRAGMA user_version").fetchone()[0],base_version)

    def test_import_relations_and_idempotency(self):
        report=import_catalog_csv(self.db,rows_bytes(sample()),dry_run=False)
        self.assertEqual(report,{"stores":1,"products":1,"skus":1,"unchanged":0})
        self.assertEqual(import_catalog_csv(self.db,rows_bytes(sample()),dry_run=False)["unchanged"],1)
        row=list_skus(self.db,store_code="SHOP-1")[0]
        self.assertEqual(row["参数"]["hole_spacing_mm"],"200")
        self.assertEqual(catalog_summary(self.db)["counts"]["skus"],1)

    def test_two_stores_same_sku_code_are_distinct(self):
        two=sample(**{"店铺编码":"SHOP-2","店铺名称":"二店","SKU编码":"GL-300-200"})
        import_catalog_csv(self.db,rows_bytes(sample(),two),dry_run=False)
        self.assertEqual(catalog_summary(self.db)["counts"]["stores"],2)
        self.assertEqual(catalog_summary(self.db)["counts"]["skus"],2)

    def test_dry_run_preserves_nonexistent_and_existing_db(self):
        self.assertFalse(self.db.exists())
        report=import_catalog_csv(self.db,rows_bytes(sample()),dry_run=True)
        self.assertEqual(report["skus"],1)
        self.assertFalse(self.db.exists())
        initialize_catalog(self.db)
        with open_database(self.db) as conn: before=conn.execute("SELECT count(*) FROM catalog_stores").fetchone()[0]
        import_catalog_csv(self.db,rows_bytes(sample()),dry_run=True)
        with open_database(self.db) as conn: after=conn.execute("SELECT count(*) FROM catalog_stores").fetchone()[0]
        self.assertEqual(before,after)

    def test_rollback_if_any_row_conflicts(self):
        first=sample()
        bad=sample(**{"店铺编码":"SHOP-1","店铺名称":"另一个店铺","SKU编码":"SKU-2"})
        with self.assertRaisesRegex(ValueError,"第3行"):
            import_catalog_csv(self.db,rows_bytes(first,bad),dry_run=False)
        self.assertEqual(catalog_summary(self.db)["counts"]["stores"],0)
        self.assertEqual(catalog_summary(self.db)["counts"]["events"],0)

    def test_existing_sku_specs_do_not_silently_change(self):
        import_catalog_csv(self.db,rows_bytes(sample()),dry_run=False)
        changed=sample(**{"孔距(mm)":"250"})
        with self.assertRaisesRegex(ValueError,"参数不同"):
            import_catalog_csv(self.db,rows_bytes(changed),dry_run=False)
        self.assertEqual(list_skus(self.db)[0]["参数"]["hole_spacing_mm"],"200")

    def test_reject_formula_invalid_length_unknown_platform(self):
        for change in ({"材质":"=HYPERLINK('evil')"},{"总长(mm)":"228mm"},{"平台":"未知"}):
            with self.subTest(change=change):
                with self.assertRaises(ValueError):import_catalog_csv(self.db,rows_bytes(sample(**change)),dry_run=True)

    def test_unknown_header_and_many_rows_rejected(self):
        self.assertTrue(csv_template().startswith(b"\xef\xbb\xbf"))
        with self.assertRaises(ValueError):import_catalog_csv(self.db,b"abc,def\na,b\n",dry_run=True)
        with self.assertRaises(ValueError):import_catalog_csv(self.db,rows_bytes(*[sample(**{"SKU编码":f"T-{i}"}) for i in range(501)]),dry_run=True)

    def test_attach_asset_only_stores_metadata_and_links_job(self):
        import_catalog_csv(self.db,rows_bytes(sample()),dry_run=False)
        sku_id=list_skus(self.db)[0]["sku_id"]
        data=b"binary photo never goes to DB"
        sha=hashlib.sha256(data).hexdigest()
        asset=attach_asset(self.db,sku_id=sku_id,kind="原尺寸图",filename="200mm.png",sha256=sha,width=1024,height=1024)
        self.assertEqual(attach_asset(self.db,sku_id=sku_id,kind="原尺寸图",filename="200mm.png",sha256=sha),asset)
        self.assertEqual(catalog_summary(self.db)["counts"]["assets"],1)
        record=new_record([("SKU.jpg",b"fake",{})],fingerprint="b"*64,platform="天猫",template="蓝白")
        save_job(self.db,record)
        link_job_sku(self.db,job_id=record["id"],sku_id=sku_id)
        link_job_sku(self.db,job_id=record["id"],sku_id=sku_id)
        self.assertEqual(catalog_summary(self.db)["counts"]["job_links"],1)
        with open_database(self.db) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM catalog_events").fetchone()[0],5)
            self.assertNotIn(data,conn.execute("SELECT details_json FROM catalog_events ORDER BY event_id DESC LIMIT 1").fetchone()[0].encode())

    def test_foreign_keys_and_event_protection(self):
        initialize_catalog(self.db)
        with open_database(self.db) as conn:
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute("INSERT INTO catalog_job_skus(job_id,sku_id,linked_utc) VALUES('x','y','2026')")
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute("INSERT INTO catalog_skus(id,store_id,product_id,code,model,specs_json,created_utc) VALUES('x','wrong','bad','sku','','{}','2026')")
        import_catalog_csv(self.db,rows_bytes(sample()),dry_run=False)
        with open_database(self.db) as conn:
            with self.assertRaises(sqlite3.IntegrityError):conn.execute("DELETE FROM catalog_events")
            with self.assertRaises(sqlite3.IntegrityError):conn.execute("UPDATE catalog_events SET action='alter'")

    def test_readonly_queries_do_not_create_database(self):
        with self.assertRaises(ValueError):catalog_summary(self.db)
        with self.assertRaises(ValueError):list_skus(self.db)
        self.assertFalse(self.db.exists())

    def test_query_uses_parameters_not_wildcards_or_sql(self):
        import_catalog_csv(self.db,rows_bytes(sample()),dry_run=False)
        self.assertEqual(list_skus(self.db,search="%' OR 1=1 --"),[])
        self.assertEqual(list_skus(self.db,search="%"),[])
        self.assertEqual(len(list_skus(self.db,search="GL-300")),1)

    def test_db_structure_mismatch_refused(self):
        initialize_catalog(self.db)
        with open_database(self.db) as conn:
            conn.execute("DELETE FROM catalog_meta WHERE key='schema_version'")
        with self.assertRaises(RuntimeError):initialize_catalog(self.db)

    def test_catalog_audit_detects_corrupt_sku_specs(self):
        import_catalog_csv(self.db,rows_bytes(sample()),dry_run=False)
        sku_id=list_skus(self.db)[0]["sku_id"]
        self.assertTrue(catalog_audit(self.db)["ok"])
        with open_database(self.db) as conn:
            conn.execute("UPDATE catalog_skus SET specs_json='bad json' WHERE id=?",(sku_id,))
        report=catalog_audit(self.db)
        self.assertFalse(report["ok"])
        self.assertTrue(any("参数JSON" in problem for problem in report["findings"]))

    def test_catalog_audit_reports_unlinked_legacy_jobs_without_claiming_corruption(self):
        record=new_record([("SKU.jpg",b"fake",{})],fingerprint="c"*64,platform="天猫",template="蓝白")
        save_job(self.db,record)
        initialize_catalog(self.db)
        report=catalog_audit(self.db)
        self.assertTrue(report["ok"])
        self.assertEqual(report["unlinked_legacy_jobs"],1)

    def test_asset_rejects_unsafe_names_and_wrong_sha(self):
        import_catalog_csv(self.db,rows_bytes(sample()),dry_run=False)
        sku_id=list_skus(self.db)[0]["sku_id"]
        with self.assertRaises(ValueError):attach_asset(self.db,sku_id=sku_id,kind="原尺寸图",filename="../evil.png",sha256="a"*64)
        with self.assertRaises(ValueError):attach_asset(self.db,sku_id=sku_id,kind="原尺寸图",filename="okay.png",sha256="invalid")
        self.assertEqual(catalog_summary(self.db)["counts"]["assets"],0)

    def test_dry_run_rejects_symlink_database(self):
        if not hasattr(Path,"symlink_to"):
            self.skipTest("no symlinks")
        initialize_catalog(self.db)
        link=self.root/"link.sqlite3"
        try:link.symlink_to(self.db)
        except OSError:self.skipTest("no symlink permissions")
        with self.assertRaises(ValueError):import_catalog_csv(link,rows_bytes(sample()),dry_run=True)

    def test_cli_smoke(self):
        command=[sys.executable,str(ROOT/"scripts/catalog_admin.py"),"--database",str(self.db)]
        template=self.root/"template.csv"
        self.assertEqual(subprocess.run([*command,"template","--output",str(template)],capture_output=True).returncode,0)
        self.assertTrue(template.read_bytes().startswith(b"\xef\xbb\xbf"))
        path=self.root/"data.csv";path.write_bytes(rows_bytes(sample()))
        res=subprocess.run([*command,"import-csv","--input",str(path)],capture_output=True)
        self.assertEqual(res.returncode,0,res.stderr.decode())
        self.assertFalse(self.db.exists())
        res=subprocess.run([*command,"import-csv","--input",str(path),"--apply"],capture_output=True)
        self.assertEqual(res.returncode,0,res.stderr.decode())
        self.assertEqual(subprocess.run([*command,"check"],capture_output=True).returncode,0)

if __name__ == "__main__":unittest.main()
