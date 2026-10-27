import json
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from ecom_images.generator import SIZES, build_job, expand_jobs, run_config


class ImageGeneratorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        (self.base / "input").mkdir()
        img = Image.new("RGBA", (400, 600), (0, 0, 0, 0))
        ImageDraw.Draw(img).rectangle((100, 100, 300, 500), fill="#42668F")
        img.save(self.base / "input" / "sample.png")

    def test_all_modes_dimensions(self):
        for mode, (w, h) in SIZES.items():
            with self.subTest(mode=mode):
                job = {
                    "mode": mode, "source": "input/sample.png",
                    "output": f"out/{mode}.jpg", "title": "示例锁具",
                    "selling_points": ["查看具体规格"],
                    "specs": [{"label": "型号", "value": "ABC"}],
                }
                result = build_job(job, self.base)
                self.assertEqual((result["width"], result["height"]), (w, h))
                with Image.open(result["file"]) as img:
                    self.assertEqual(img.size, (w, h))
                if mode == "search_white":
                    self.assertLess(result["bytes"], 3_000_000)
                    with Image.open(result["file"]) as img:
                        self.assertTrue(all(v >= 251 for v in img.getpixel((0, 0))))

    def test_small_transparent_logo(self):
        logo = Image.new("RGBA", (150, 60), (0, 0, 0, 0))
        ImageDraw.Draw(logo).rectangle((5, 5, 145, 55), fill="#456789")
        logo.save(self.base / "input" / "logo.png")
        result = build_job({"mode": "main", "source": "input/sample.png",
                            "logo": "input/logo.png", "output": "out/logo.jpg",
                            "title": "带Logo的商品"}, self.base)
        self.assertEqual(result["width"], 1440)

    def test_white_rejects_environment_photo(self):
        Image.new("RGB", (500, 500), "#938F7A").save(self.base / "input" / "photo.jpg")
        with self.assertRaisesRegex(ValueError, "透明 PNG 或干净白底"):
            build_job({"mode": "search_white", "source": "input/photo.jpg",
                       "output": "out/should_not_exist.jpg"}, self.base)

    def test_preserves_input_file(self):
        image_path = self.base / "input" / "sample.png"
        data = image_path.read_bytes()
        build_job({"mode": "sku", "source": "input/sample.png",
                   "title": "请核对", "output": "out/a.png"}, self.base)
        self.assertEqual(data, image_path.read_bytes())

    def test_batch(self):
        (self.base / "input" / "second.png").write_bytes(
            (self.base / "input" / "sample.png").read_bytes())
        config = {"jobs": [{"mode": "sku", "title": "{stem} 规格图",
                            "source_glob": "input/*.png",
                            "output_pattern": "out/{stem}_sku.jpg"}]}
        jobs = expand_jobs(config, self.base)
        self.assertEqual(len(jobs), 2)
        self.assertEqual({j["title"] for j in jobs},
                         {"sample 规格图", "second 规格图"})
        file = self.base / "config.json"
        file.write_text(json.dumps(config), encoding="utf-8")
        self.assertEqual(len(run_config(file, self.base)), 2)

    def test_no_overwrite_source(self):
        with self.assertRaisesRegex(ValueError, "不能覆盖"):
            build_job({"mode": "search_white", "source": "input/sample.png",
                       "output": "input/sample.png"}, self.base)

    def test_no_unverified_spec_injection(self):
        with self.assertRaisesRegex(ValueError, "SKU 模式必须提供 title"):
            build_job({"mode": "sku", "source": "input/sample.png",
                       "output": "out/a.jpg"}, self.base)


if __name__ == "__main__":
    unittest.main()
