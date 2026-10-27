"""A complete no-network production rehearsal with synthetic industrial hardware."""
from __future__ import annotations

import hashlib
import io
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from test_sku_batch import fake_xlsx, basic_row
from ecom_images.workflow import UploadedPicture
from ecom_images.sku_preflight_v6 import inspect_batch
from ecom_images.sku_batch import build_sku_batch
from ecom_images.sku_review_v5 import FIELDS, audit_reviews, review_rows, review_zip
from ecom_images.production_ledger_v6 import new_record, record_review, save_record, list_records


def handle_photo(name='LS_handle.png', measurement=False):
    canvas = Image.new('RGBA', (600, 400), (0, 0, 0, 0))
    d = ImageDraw.Draw(canvas)
    if measurement:
        d.line((40, 340, 560, 340), fill='#0D7FF4', width=4)
        d.line((40, 320, 40, 360), fill='#0D7FF4', width=3)
        d.line((560, 320, 560, 360), fill='#0D7FF4', width=3)
        d.text((260, 355), '200 mm', fill='black')
    else:
        d.rounded_rectangle((40, 160, 560, 220), radius=23, fill='#ACB2BA', outline='#616F7A', width=6)
        for x in (70, 530):
            d.ellipse((x-12, 176, x+12, 200), fill='#2D414D')
    out = io.BytesIO()
    canvas.save(out, 'PNG')
    return UploadedPicture(name, out.getvalue())


class E2EWorkflowTests(unittest.TestCase):
    def test_two_sku_import_render_quality_approval_zip_and_local_history(self):
        sku1 = basic_row(sku='LS-200', photo='LS_handle.png', hole='200', length='228')
        sku2 = basic_row(sku='LS-250', photo='LS_handle.png', hole='250', length='278')
        sheet = fake_xlsx([sku1 + ['LS_dimensions.png'], sku2 + ['LS_dimensions.png']])
        images = [handle_photo(), handle_photo('LS_dimensions.png', measurement=True)]
        check = inspect_batch(sheet, images, template_style='蓝白工业参数风')
        self.assertEqual((check.ready, check.blocked), (2, 0))
        allowed = frozenset(row['Excel行号'] for row in check.rows if row['状态'] == '可生成')
        out = build_sku_batch(sheet, images, template_style='蓝白工业参数风', allowed_row_numbers=allowed)
        self.assertEqual((out.successes, out.failures), (2, 0))
        self.assertEqual(len({name for name, _, _ in out.images}), 2)
        for name, data, meta in out.images:
            with Image.open(io.BytesIO(data)) as pic:
                self.assertEqual(pic.size, (1440, 1440))
            self.assertEqual(meta['dimension_source'], 'LS_dimensions.png')
            self.assertIn('手机端', meta['dimension_text_legibility'])
        with zipfile.ZipFile(io.BytesIO(out.zip_bytes())) as archive:
            self.assertIn('quality_report.json', archive.namelist())
        job = new_record(out.images, fingerprint='f'*64, platform='淘宝 / 天猫', template='蓝白工业参数风')
        approval = review_rows(out.images)
        for row in approval:
            row.update({key: True for key in FIELDS})
            row['审核结论'] = '通过'
        report = audit_reviews(out.images, approval)
        self.assertTrue(report['ready_to_publish'])
        checked = record_review(job, out.images, report, reviewer='本地模拟验收员')
        self.assertEqual(checked['stage'], '全部审核通过')
        with tempfile.TemporaryDirectory() as folder:
            save_record(Path(folder), checked)
            self.assertEqual(len(list_records(Path(folder))), 1)
        with zipfile.ZipFile(io.BytesIO(review_zip(out.images, report))) as archive:
            self.assertEqual(len([i for i in archive.namelist() if i.startswith('approved/')]), 2)

    def test_missing_drawing_blocks_only_bad_row(self):
        first = basic_row(sku='LS-200') + ['missing.png']
        second = basic_row(sku='LS-250') + ['LS_dimensions.png']
        sheet = fake_xlsx([first, second])
        photos = [handle_photo('handle.png'), handle_photo('LS_dimensions.png', measurement=True)]
        check = inspect_batch(sheet, photos, template_style='灰白极简技术风')
        self.assertEqual((check.ready, check.blocked), (1, 1))
        allowed = frozenset(row['Excel行号'] for row in check.rows if row['状态'] == '可生成')
        out = build_sku_batch(sheet, photos, template_style='灰白极简技术风', allowed_row_numbers=allowed)
        self.assertEqual((out.successes, out.failures), (1, 1))
        self.assertIn('预检查未通过', out.rows[0]['message'])


if __name__ == '__main__':
    unittest.main()
