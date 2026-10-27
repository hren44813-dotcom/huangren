"""验证自动质检只报告可机器核验的客观事实。"""
import io
import json
import sys
import unittest
import zipfile
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from ecom_images.quality import audit_export
from ecom_images.session_guard import input_fingerprint
from ecom_images.workflow import BatchResult, UploadedPicture


def jpeg(w: int, h: int, color: str = "white") -> bytes:
    stream = io.BytesIO()
    Image.new("RGB", (w, h), color).save(stream, "JPEG")
    return stream.getvalue()


class QualityTests(unittest.TestCase):
    def test_main_image_passes_automated_checks_but_manual_pending(self):
        out = audit_export("main.jpg", jpeg(1440, 1440), "main")
        self.assertTrue(out["auto_pass"])
        self.assertEqual(out["manual_status"], "pending")
        self.assertIn("孔位", out["manual_review"][0])

    def test_wrong_dimensions_detected(self):
        out = audit_export("main.jpg", jpeg(800, 800), "main")
        self.assertFalse(out["auto_pass"])
        self.assertIn("尺寸", [c["item"] for c in out["checks"] if not c["passed"]])

    def test_mislabelled_format_detected(self):
        out = audit_export("main.png", jpeg(1440, 1440), "main")
        self.assertFalse(out["auto_pass"])

    def test_white_edge_detects_colored_border(self):
        out = audit_export("search.jpg", jpeg(1440, 1440, "black"), "search_white")
        self.assertFalse(out["auto_pass"])
        self.assertIn("白底边缘抽样", [c["item"] for c in out["checks"] if not c["passed"]])

    def test_corrupt_image_fails_without_crash(self):
        out = audit_export("broken.jpg", b"not an image", "main")
        self.assertFalse(out["auto_pass"])
        self.assertEqual(out["manual_status"], "pending")

    def test_zip_contains_qa_and_original_report(self):
        images = [("item/main_01.jpg", jpeg(1440, 1440), {"mode": "main", "width": 1440, "height": 1440})]
        result = BatchResult(images=images)
        with zipfile.ZipFile(io.BytesIO(result.zip_bytes())) as z:
            self.assertEqual(set(z.namelist()), {"item/main_01.jpg", "report.json", "quality_report.json"})
            report = json.loads(z.read("quality_report.json"))
            self.assertEqual(report["summary"]["auto_pass"], 1)
            self.assertEqual(report["summary"]["manual_review_pending"], 1)

    def test_input_fingerprint_changes_with_image_and_form(self):
        pictures = [UploadedPicture("img.png", b"abcdef")]
        a = input_fingerprint(pictures, {"title": "锁具"})
        self.assertEqual(a, input_fingerprint(pictures, {"title": "锁具"}))
        self.assertNotEqual(a, input_fingerprint(pictures, {"title": "铰链"}))
        self.assertNotEqual(a, input_fingerprint([UploadedPicture("img.png", b"abcdeF")], {"title": "锁具"}))
        self.assertNotEqual(a, input_fingerprint(pictures, {"title": "锁具"}, UploadedPicture("logo.png", b"1")))


if __name__ == "__main__":
    unittest.main()
