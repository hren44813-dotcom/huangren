"""V13: reference catalog never silently creates or overwrites sales SKUs."""
import copy, json, sqlite3, sys, tempfile, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from ecom_images.history_reference_v13 import initialize_history,import_reference,list_reference,history_integrity,link_verified_sku
from ecom_images.database_v9 import open_database

class HistoryReferenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw=(ROOT/'assets/history/history_reference_v13.json').read_bytes()
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.db=Path(self.tmp.name)/'records.sqlite3'
        initialize_history(self.db)
    def test_import74_and23options(self):
        r=import_reference(self.db,self.raw)
        self.assertEqual(r['inserted'],74)
        self.assertTrue(history_integrity(self.db)['ok'])
        with open_database(self.db) as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM history_ref_options').fetchone()[0],23)
            self.assertEqual(conn.execute('SELECT count(*) FROM jobs').fetchone()[0],0)
    def test_second_import_is_noop(self):
        import_reference(self.db,self.raw)
        self.assertEqual(import_reference(self.db,self.raw)['unchanged'],74)
    def test_dry_run_is_read_only(self):
        self.assertEqual(import_reference(self.db,self.raw,dry_run=True)['would_insert'],74)
        with open_database(self.db) as c:self.assertEqual(c.execute('SELECT count(*) FROM history_ref_items').fetchone()[0],0)
    def test_dry_run_on_missing_db_creates_nothing(self):
        dest=Path(self.tmp.name)/'missing.sqlite3'
        self.assertEqual(import_reference(dest,self.raw,dry_run=True)['would_insert'],74)
        self.assertFalse(dest.exists())
    def test_detect_conflict_rollback(self):
        import_reference(self.db,self.raw)
        obj=json.loads(self.raw)
        obj['records'][3]['notes']='改动'
        with self.assertRaisesRegex(ValueError,'有冲突'):
            import_reference(self.db,json.dumps(obj,ensure_ascii=False).encode())
        self.assertEqual(history_integrity(self.db)['records'],74)
    def test_refuses_fake_release(self):
        obj=json.loads(self.raw);obj['records'][0]['release_status']='核验通过'
        with self.assertRaisesRegex(ValueError,'未核验'):
            import_reference(self.db,json.dumps(obj,ensure_ascii=False).encode())
    def test_search_and_like_literal(self):
        import_reference(self.db,self.raw)
        r=list_reference(self.db,text='MS705');self.assertEqual(len(r),4)
        self.assertEqual(list_reference(self.db,text='%'),[])
        self.assertEqual(len(list_reference(self.db,category='阻尼转轴')),14)
    def test_integrity_detects_payload_tamper(self):
        import_reference(self.db,self.raw)
        with open_database(self.db) as c:c.execute("UPDATE history_ref_items SET payload_json='{}' WHERE model='MS705'")
        self.assertFalse(history_integrity(self.db)['ok'])
    def test_no_auto_sku_link(self):
        import_reference(self.db,self.raw)
        with open_database(self.db) as c:self.assertEqual(c.execute('SELECT count(*) FROM history_ref_links').fetchone()[0],0)
        with self.assertRaises(ValueError):link_verified_sku(self.db,history_id='H-'+'0'*20,sku_id='bad',verified_by='A',evidence_note='依据图纸')

if __name__=='__main__':unittest.main()
