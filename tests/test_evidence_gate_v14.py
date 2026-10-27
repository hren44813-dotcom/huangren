"""Original evidence, record-grain, and publish-gate regression tests."""
import copy
import sys
import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from ecom_images.evidence_gate_v14 import audit, inspect, export_csv
import json

class SourceGateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.history=json.loads((ROOT/'assets/history/history_reference_v13.json').read_text(encoding='utf-8'))
        cls.seed=json.loads((ROOT/'assets/history/evidence_seed_v14.json').read_text(encoding='utf-8'))
    def test_complete_history_unchanged(self):
        r=audit();self.assertEqual((r['history_records'],r['model_records']), (74,60))
    def test_only_six_page_locators(self):
        r=audit();self.assertEqual((r['page_located_records'],r['unlocated_records']), (6,68))
    def test_no_engineering_approval(self):
        r=audit();self.assertEqual((r['independently_engineering_verified_count'],r['commercial_sku_confirmed_count']), (0,0))
    def test_reject_attribute_escalation(self):
        s=copy.deepcopy(self.seed);s['claims'][0]['field']='material'
        with self.assertRaises(AssertionError):inspect(self.history,s)
    def test_reject_wrong_source_model(self):
        s=copy.deepcopy(self.seed);s['claims'][0]['value']='MS731-9'
        with self.assertRaises(AssertionError):inspect(self.history,s)
    def test_reject_missing_history_record(self):
        s=copy.deepcopy(self.seed);s['claims'][0]['history_id']='H-'+('0'*20)
        with self.assertRaises(AssertionError):inspect(self.history,s)
    def test_csv_74_rows(self):
        r=audit();csv=export_csv(r).decode('utf-8-sig')
        self.assertEqual(len(csv.strip().splitlines()),75)
        self.assertIn('GL1-336',csv)
if __name__=='__main__':unittest.main()
