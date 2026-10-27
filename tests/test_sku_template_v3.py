"""V3 模板测试：不重画尺寸图、不借图替代、不编造未填写的信息。"""
from __future__ import annotations

import io
import json
import sys
import unittest
import zipfile
from pathlib import Path

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from ecom_images.sku_batch import COLUMNS, build_sku_batch, read_sku_rows
from ecom_images.sku_template_v3 import THEMES, render_sku_template
from ecom_images.workflow import UploadedPicture
from test_sku_batch import fake_xlsx, picture


def row(sku="R-001", dimension="dimension.png", name="工业拉手"):
    return [sku, name, "handle.png", "样品型号", "200", "228", "", "", "", "", dimension]


def dimension_png():
    image = Image.new("RGBA", (600, 450), (255, 255, 255, 255))
    draw = ImageDraw.Draw(image)
    draw.rectangle((50, 120, 550, 300), outline="black", width=6)
    draw.line((55, 345, 545, 345), fill="#0D7FF4", width=8)
    stream = io.BytesIO()
    image.save(stream, "PNG")
    return UploadedPicture("dimension.png", stream.getvalue())


class SkuV3Tests(unittest.TestCase):
    def test_exactly_three_presets(self):
        self.assertEqual(list(THEMES), ["蓝白工业参数风", "黄黑工业风", "灰白极简技术风"])
        self.assertEqual(THEMES["黄黑工业风"].header_text, "#111820")

    def test_template_outputs_full_size_image(self):
        for style in THEMES:
            with self.subTest(style=style):
                raw, metadata = render_sku_template(picture(), drawing=dimension_png(),
                                                    title="工业拉手", specs=[{"label":"孔距", "value":"200 mm"}], style=style)
                with Image.open(io.BytesIO(raw)) as im:
                    self.assertEqual(im.size, (1440, 1440))
                    self.assertEqual(im.format, "JPEG")
                self.assertEqual(metadata["dimension_source"], "dimension.png")
                self.assertTrue(metadata["manual_review_required"])

    def test_no_fabricated_dimension(self):
        raw, meta = render_sku_template(picture(), title="真实标题", specs=[])
        self.assertIsNone(meta["dimension_source"])
        with Image.open(io.BytesIO(raw)) as image:
            self.assertEqual(image.size, (1440, 1440))

    def test_bad_preset_rejected(self):
        with self.assertRaisesRegex(ValueError, "未知"):
            render_sku_template(picture(), title="正常标题", specs=[], style="dangerous")

    def test_batch_missing_dimension_fails_only_own_row(self):
        excel = fake_xlsx([row("A"), row("B", "")])
        result = build_sku_batch(excel, [picture(), dimension_png()], template_style="灰白极简技术风")
        self.assertEqual((result.successes, result.failures), (2, 0))
        missing = build_sku_batch(excel, [picture()], template_style="灰白极简技术风")
        self.assertEqual((missing.successes, missing.failures), (1, 1))
        self.assertIn("原尺寸图", missing.rows[0]["message"])
        with zipfile.ZipFile(io.BytesIO(missing.zip_bytes())) as z:
            self.assertIn("quality_report.json", z.namelist())
            self.assertEqual(json.loads(z.read("quality_report.json"))["summary"]["manual_review_pending"], 1)

    def test_existing_v2_excel_is_compatible(self):
        earlier_fields = COLUMNS[:-1]
        excel = fake_xlsx([row("A")[:-1]], columns=earlier_fields)
        result = build_sku_batch(excel, [picture()], template_style="蓝白工业参数风")
        self.assertEqual(result.successes, 1)
        self.assertIsNone(result.images[0][2]["dimension_source"])

    def test_missing_or_path_dimension_never_fallback(self):
        for filename in ("../dimension.png", "missing.png"):
            with self.subTest(filename=filename):
                result = build_sku_batch(fake_xlsx([row(dimension=filename)]), [picture(), dimension_png()], template_style="蓝白工业参数风")
                self.assertEqual(result.failures, 1)

    def test_blank_v3_template(self):
        path = Path(__file__).resolve().parents[1] / "assets/templates/sku_import_template_v3.xlsx"
        self.assertTrue(path.exists())
        with self.assertRaisesRegex(ValueError, "没有数据"):
            read_sku_rows(path.read_bytes())


if __name__ == "__main__":
    unittest.main()
