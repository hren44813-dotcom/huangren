import csv
import io
import json
import sys
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from ecom_images.sku_review_v5 import FIELDS, audit_reviews, review_csv, review_rows, review_zip


class ReviewV5Tests(unittest.TestCase):
    def setUp(self):
        self.pictures = [('SKU_X.jpg', b'synthetic-test-file-1', {}), ('SKU_Y.jpg', b'synthetic-test-file-2', {})]

    def test_default_pending_not_approved(self):
        report = audit_reviews(self.pictures, review_rows(self.pictures))
        self.assertFalse(report['ready_to_publish'])
        self.assertEqual(report['counts']['待审核'], 2)

    def test_need_four_checks_to_approve(self):
        rows = review_rows(self.pictures)
        rows[0]['审核结论'] = '通过'
        with self.assertRaisesRegex(ValueError, '全部4项'):
            audit_reviews(self.pictures, rows)

    def test_approved_partial_only_in_zip(self):
        rows = review_rows(self.pictures)
        rows[0].update({k: True for k in FIELDS})
        rows[0]['审核结论'] = '通过'
        rows[1]['审核结论'] = '返工'
        rows[1]['备注'] = '尺寸标注需要核实'
        report = audit_reviews(self.pictures, rows)
        self.assertFalse(report['ready_to_publish'])
        with zipfile.ZipFile(io.BytesIO(review_zip(self.pictures, report))) as archive:
            self.assertIn('approved/SKU_X.jpg', archive.namelist())
            self.assertNotIn('approved/SKU_Y.jpg', archive.namelist())
            self.assertIn('review_report.csv', archive.namelist())
            self.assertIn('review_report.json', archive.namelist())
            self.assertEqual(json.loads(archive.read('review_report.json'))['counts']['通过'], 1)

    def test_all_approved_but_generated_failures(self):
        rows = review_rows(self.pictures)
        for row in rows:
            row.update({k: True for k in FIELDS})
            row['审核结论'] = '通过'
        self.assertTrue(audit_reviews(self.pictures, rows)['ready_to_publish'])
        self.assertFalse(audit_reviews(self.pictures, rows, failed_generation=1)['ready_to_publish'])

    def test_invalid_and_duplicate(self):
        rows = review_rows(self.pictures)
        rows[1]['文件名'] = rows[0]['文件名']
        with self.assertRaises(ValueError):
            audit_reviews(self.pictures, rows)
        rows = review_rows(self.pictures)
        rows[0]['产品结构'] = '是'
        with self.assertRaises(ValueError):
            audit_reviews(self.pictures, rows)

    def test_formula_escape(self):
        rows = review_rows(self.pictures)
        rows[0]['备注'] = '=HYPERLINK("bad")'
        report = audit_reviews(self.pictures, rows)
        text = review_csv(report).decode('utf-8-sig')
        self.assertIn("'=HYPERLINK", text)

    def test_note_limit(self):
        rows = review_rows(self.pictures)
        rows[0]['备注'] = 'x'*501
        with self.assertRaises(ValueError):
            audit_reviews(self.pictures, rows)

    def test_empty_batch_not_ready(self):
        self.assertFalse(audit_reviews([], [])['ready_to_publish'])


if __name__ == '__main__':
    unittest.main()
