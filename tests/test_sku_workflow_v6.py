"""V6 工作流验收：批前校验、审核防串批、任务流水。"""
import hashlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from ecom_images.sku_batch import SkuRow
from ecom_images.sku_preflight_v6 import inspect_batch
from ecom_images.production_ledger_v6 import (
    list_records, new_record, record_review, save_record,
)
from ecom_images.sku_review_v5 import (
    FIELDS, audit_reviews, review_rows, review_signature, review_zip,
)
from ecom_images.workflow import UploadedPicture


def photo(name: str) -> UploadedPicture:
    with io.BytesIO() as out:
        Image.new("RGB", (150, 120), "white").save(out, format="PNG")
        return UploadedPicture(name, out.getvalue())


def data_row(sku="LS-001", photo_name="handle.png", drawing=""):
    return SkuRow(2, {"SKU编码": sku, "商品名称": "工业机床拉手",
                      "图片文件名": photo_name, "尺寸图文件名": drawing,
                      "型号": "LS-001", "孔距(mm)": "200", "总长(mm)": "228",
                      "材质": "", "表面处理": "", "色块颜色": "#0D7FF4", "标题字色": "#FFFFFF"})


class WorkflowV6Tests(unittest.TestCase):
    def setUp(self):
        self.images = [("SKU_LS001.jpg", b"example-image-data", {})]
        self.fingerprint = "f" * 64

    @patch("ecom_images.sku_preflight_v6.read_sku_rows")
    def test_preflight_good_row(self, rows):
        rows.return_value = [data_row()]
        report = inspect_batch(b"sample", [photo("handle.png")])
        self.assertEqual((report.ready, report.blocked), (1, 0))

    @patch("ecom_images.sku_preflight_v6.read_sku_rows")
    def test_missing_photo_never_replaced(self, rows):
        rows.return_value = [data_row(photo_name="missing.png")]
        result = inspect_batch(b"sample", [photo("handle.png")])
        self.assertEqual(result.blocked, 1)
        self.assertIn("不匹配", result.rows[0]["原因"])

    @patch("ecom_images.sku_preflight_v6.read_sku_rows")
    def test_missing_drawing_in_custom_style(self, rows):
        rows.return_value = [data_row(drawing="measurement.png")]
        report = inspect_batch(b"sample", [photo("handle.png")], template_style="蓝白工业参数风")
        self.assertEqual(report.blocked, 1)
        self.assertIn("尺寸图", report.rows[0]["原因"])

    @patch("ecom_images.sku_preflight_v6.read_sku_rows")
    def test_duplicate_sku_and_bad_dimensions_are_row_errors(self, rows):
        bad = data_row(sku="LS-001")
        bad.data["孔距(mm)"] = "1+1"
        rows.return_value = [data_row(), bad]
        report = inspect_batch(b"sample", [photo("handle.png")])
        self.assertEqual((report.ready, report.blocked), (1, 1))
        self.assertIn("重复", report.rows[1]["原因"])
        self.assertIn("孔距", report.rows[1]["原因"])

    @patch("ecom_images.sku_preflight_v6.read_sku_rows")
    def test_bad_image_file_and_duplicate_name(self, rows):
        rows.return_value = [data_row()]
        broken = UploadedPicture("handle.png", b"not-an-image")
        report = inspect_batch(b"fake", [broken])
        self.assertEqual(report.blocked, 1)
        with self.assertRaisesRegex(ValueError, "重名"):
            inspect_batch(b"fake", [photo("handle.png"), photo("HANDLE.PNG")])

    def test_record_only_metadata_and_history(self):
        record = new_record(self.images, fingerprint=self.fingerprint, platform="天猫", template="蓝白")
        with tempfile.TemporaryDirectory() as temp:
            filename = save_record(Path(temp), record)
            self.assertTrue(filename.exists())
            raw = filename.read_text(encoding="utf-8")
            self.assertNotIn("example-image-data", raw)
            self.assertIn(hashlib.sha256(self.images[0][1]).hexdigest(), raw)
            self.assertEqual(list_records(Path(temp))[0]["阶段"], "待人工审核")

    def test_invalid_id_and_fingerprint_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "指纹"):
            new_record(self.images, fingerprint="short", platform="天猫", template="蓝白")
        with self.assertRaisesRegex(ValueError, "编号"):
            new_record(self.images, fingerprint=self.fingerprint, platform="天猫",
                       template="蓝白", batch_id="../../bad")

    def test_human_approval_saved_and_stale_rejected(self):
        record = new_record(self.images, fingerprint=self.fingerprint, platform="天猫", template="蓝白")
        rows = review_rows(self.images)
        rows[0].update({k: True for k in FIELDS})
        rows[0]["审核结论"] = "通过"
        report = audit_reviews(self.images, rows)
        approved = record_review(record, self.images, report, reviewer="审核员A")
        self.assertEqual(approved["stage"], "全部审核通过")
        with tempfile.TemporaryDirectory() as td:
            save_record(Path(td), approved)
            self.assertEqual(list_records(Path(td))[0]["阶段"], "全部审核通过")
        altered = [("SKU_LS001.jpg", b"DIFFERENT", {})]
        with self.assertRaisesRegex(ValueError, "内容"):
            record_review(record, altered, report, reviewer="审核员A")
        with self.assertRaises(ValueError):
            review_zip(altered, report)

    def test_modified_report_cannot_get_approved_zip(self):
        rows = review_rows(self.images)
        rows[0].update({k: True for k in FIELDS})
        rows[0]["审核结论"] = "通过"
        report = audit_reviews(self.images, rows)
        self.assertTrue(review_zip(self.images, report))
        report["rows"][0]["image_sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "不一致"):
            review_zip(self.images, report)

    def test_partial_review_and_failed_generation(self):
        first = self.images + [("SKU_LS002.jpg", b"other", {})]
        record = new_record(first, fingerprint=self.fingerprint, platform="天猫",
                            template="灰白", failed_generation=1)
        rows = review_rows(first)
        rows[0].update({k: True for k in FIELDS})
        rows[0]["审核结论"] = "通过"
        rows[1]["审核结论"] = "返工"
        rows[1]["备注"] = "尺寸需要核实"
        report = audit_reviews(first, rows, failed_generation=1)
        amended = record_review(record, first, report, reviewer="审核员B")
        self.assertEqual(amended["stage"], "返工中")
        self.assertFalse(amended["review"]["ready_to_publish"])

    def test_rework_requires_note_and_signature_changes(self):
        rows = review_rows(self.images)
        rows[0]["审核结论"] = "返工"
        with self.assertRaisesRegex(ValueError, "返工"):
            audit_reviews(self.images, rows)
        rows[0]["备注"] = "待调整文案"
        sig1 = review_signature(audit_reviews(self.images, rows))
        rows[0]["备注"] = "待核对尺寸"
        sig2 = review_signature(audit_reviews(self.images, rows))
        self.assertNotEqual(sig1, sig2)

    def test_report_failure_count_cannot_be_replayed(self):
        record = new_record(self.images, fingerprint=self.fingerprint, platform="天猫",
                            template="蓝白", failed_generation=2)
        report = audit_reviews(self.images, review_rows(self.images), failed_generation=0)
        with self.assertRaisesRegex(ValueError, "失败数量"):
            record_review(record, self.images, report, reviewer="审核员A")


if __name__ == "__main__":
    unittest.main()
