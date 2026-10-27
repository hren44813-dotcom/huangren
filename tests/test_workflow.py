import io
import json
import sys
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from ecom_images.ai_bridge import generate_xinghe
from ecom_images.workflow import (
    BatchResult, UploadedPicture, clean_stem, planned_count, produce_images, validate_upload,
)


def picture(name="product.png", color=(55, 99, 143, 255)):
    im = Image.new("RGBA", (400, 550), (0, 0, 0, 0))
    for y in range(130, 430):
        for x in range(120, 280):
            im.putpixel((x, y), color)
    content = io.BytesIO()
    im.save(content, format="PNG")
    return UploadedPicture(name, content.getvalue())


class WorkflowTests(unittest.TestCase):
    def test_safe_stems(self):
        self.assertEqual(clean_stem("../../MS705.png", 2), "02_MS705")
        self.assertEqual(clean_stem("C:\\private\\SKU 01.png", 1), "01_SKU_01")
        self.assertEqual(clean_stem("..", 1), "01_image")

    def test_limits(self):
        self.assertEqual(planned_count(3, ["search_white", "sku"], 2), 9)
        with self.assertRaisesRegex(ValueError, "最多生成"):
            planned_count(25, ["main", "portrait", "detail"], 4)
        with self.assertRaises(ValueError):
            planned_count(1, ["hacker"], 1)

    def test_white_and_sku_generation_and_zip(self):
        original = picture()
        old_bytes = bytes(original.data)
        result = produce_images([original], ["search_white", "sku"], 2,
                                title="MS705 锁具", specs=[{"label": "型号", "value": "MS705"}])
        self.assertEqual(result.errors, [])
        self.assertEqual(len(result.images), 3)
        self.assertEqual(original.data, old_bytes)
        for name, bytes_, meta in result.images:
            with Image.open(io.BytesIO(bytes_)) as image:
                self.assertEqual(image.size, (1440, 1440))
                if "search_white" in name:
                    self.assertEqual(image.getpixel((0, 0)), (255, 255, 255))
                    self.assertLess(len(bytes_), 3_000_000)
        with zipfile.ZipFile(io.BytesIO(result.zip_bytes())) as archive:
            filenames = archive.namelist()
            self.assertIn("report.json", filenames)
            self.assertIn("quality_report.json", filenames)
            self.assertEqual(len(filenames), 5)
            report = json.loads(archive.read("report.json"))
            self.assertEqual(len(report["success"]), 3)
            audits = json.loads(archive.read("quality_report.json"))
            self.assertEqual(audits["summary"]["auto_pass"], 3)
            self.assertEqual(audits["summary"]["manual_review_pending"], 3)

    def test_incomplete_input_does_not_stop_other_images(self):
        result = produce_images([picture("good.png"), UploadedPicture("bad.jpg", b"bad")],
                                ["portrait"], title="已知产品", variants=1)
        self.assertEqual(len(result.images), 1)
        self.assertEqual(len(result.errors), 1)

    def test_uncut_photo_rejected_for_white(self):
        mem = io.BytesIO()
        Image.new("RGB", (400, 400), "#ABCABC").save(mem, "JPEG")
        result = produce_images([UploadedPicture("photo.jpg", mem.getvalue())],
                                ["search_white"], 1)
        self.assertFalse(result.images)
        self.assertIn("透明 PNG", result.errors[0])

    def test_requires_truthful_title(self):
        with self.assertRaisesRegex(ValueError, "真实产品标题"):
            produce_images([picture()], ["sku"], 1, title="  ")

    def test_invalid_logo_rejected(self):
        with self.assertRaisesRegex(ValueError, "无效"):
            produce_images([picture()], ["main"], 1, title="产品",
                           logo=UploadedPicture("logo.png", b"not image"))

    def test_ai_no_consent_no_network(self):
        with mock.patch("subprocess.run") as run:
            with self.assertRaisesRegex(ValueError, "确认"):
                generate_xinghe(picture(), api_key="key", model="example", prompt="Test")
            run.assert_not_called()

    def test_ai_no_key_no_network(self):
        with mock.patch("subprocess.run") as run:
            with self.assertRaisesRegex(ValueError, "密钥"):
                generate_xinghe(picture(), api_key="", model="example", prompt="Test", consent=True)
            run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
