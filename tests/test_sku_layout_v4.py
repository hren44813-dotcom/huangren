"""V4 配置、原图保持和 Excel 批量兼容。"""
import io
import json
import sys
import unittest
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from ecom_images.sku_layout_v4 import (
    default_layout, layout_json, layout_from_json, preview_regions,
    render_custom_sku, validate_layout,
)
from ecom_images.sku_batch import build_sku_batch
from ecom_images.workflow import UploadedPicture
from test_sku_batch import fake_xlsx, picture
from test_sku_template_v3 import dimension_png, row


class LayoutV4Tests(unittest.TestCase):
    def test_default_presets_valid(self):
        for theme in ("蓝白工业参数风", "黄黑工业风", "灰白极简技术风"):
            with self.subTest(theme=theme):
                d = default_layout(theme)
                self.assertEqual(layout_from_json(layout_json(d)), d)

    def test_reject_overlap(self):
        d = default_layout()
        d["slots"]["drawing"] = [80, 300, 500, 600]
        with self.assertRaisesRegex(ValueError, "重叠"):
            validate_layout(d)

    def test_reject_coordinates_type(self):
        d = default_layout()
        d["slots"]["product"][0] = True
        with self.assertRaisesRegex(ValueError, "整数"):
            validate_layout(d)

    def test_reject_out_of_bounds(self):
        d = default_layout()
        d["slots"]["title"] = [25, 30, 1400, 150]
        with self.assertRaisesRegex(ValueError, "越界"):
            validate_layout(d)

    def test_reject_invalid_json_and_unknown_fields(self):
        with self.assertRaises(ValueError):
            layout_from_json(b"{broken")
        d = default_layout()
        d["script"] = "ignored?"
        with self.assertRaisesRegex(ValueError, "字段"):
            validate_layout(d)

    def test_preview_png_correct_size(self):
        raw = preview_regions(default_layout())
        with Image.open(io.BytesIO(raw)) as img:
            self.assertEqual(img.size, (1440, 1440))
            self.assertEqual(img.format, "PNG")

    def test_output_1440_and_metadata(self):
        data, meta = render_custom_sku(picture(), drawing=dimension_png(),
                                       title="工业拉手", specs=[{"label": "孔距", "value": "200 mm"}],
                                       layout=default_layout())
        with Image.open(io.BytesIO(data)) as im:
            self.assertEqual((im.size, im.format), ((1440, 1440), "JPEG"))
        self.assertEqual(meta["template_version"], 4)
        self.assertEqual(meta["dimension_source"], "dimension.png")

    def test_clean_template_must_be_exact_size(self):
        buffer = io.BytesIO()
        Image.new("RGB", (1024, 1024), "#FFFFFF").save(buffer, "PNG")
        with self.assertRaisesRegex(ValueError, "1440"):
            render_custom_sku(picture(), drawing=None, title="样品", specs=[],
                              layout=default_layout(), clean_template=UploadedPicture("blank.png", buffer.getvalue()))

    def test_v4_batch_missing_dimension_only_fails_that_row(self):
        excel = fake_xlsx([row("A"), row("B", "")])
        result = build_sku_batch(excel, [picture()], custom_layout=default_layout())
        self.assertEqual((result.successes, result.failures), (1, 1))
        self.assertEqual(result.images[0][2]["template_version"], 4)

    def test_v3_still_works(self):
        excel = fake_xlsx([row("A", "")])
        result = build_sku_batch(excel, [picture()], template_style="蓝白工业参数风")
        self.assertEqual(result.successes, 1)

    def test_conflicting_layout_settings(self):
        with self.assertRaisesRegex(ValueError, "不能同时"):
            build_sku_batch(b"bad", [picture()], template_style="蓝白工业参数风", custom_layout=default_layout())


if __name__ == "__main__":
    unittest.main()
