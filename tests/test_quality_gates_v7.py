"""V7 风险回归：预检查/生成一致性、AI 缓存、防止丢失尺寸图与错误模板。"""
import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from ecom_images.ai_result_guard_v7 import ai_request_fingerprint, valid_cached_ai_result
from ecom_images.sku_batch import SkuRow, build_sku_batch, _csv_safe
from ecom_images.sku_preflight_v6 import inspect_batch
from ecom_images.template_library_v5 import save_template, list_templates
from ecom_images.sku_layout_v4 import default_layout
from ecom_images.workflow import UploadedPicture


def photo(name="handle.png", transparent=False):
    raw = io.BytesIO()
    if transparent:
        Image.new("RGBA", (160, 130), (0, 0, 0, 0)).save(raw, "PNG")
    else:
        Image.new("RGB", (160, 130), (155, 155, 160)).save(raw, "PNG")
    return UploadedPicture(name, raw.getvalue())


def row(number, sku, pic="handle.png", drawing="", hole="200", length="228", color="#0D7FF4"):
    return SkuRow(number, {"SKU编码": sku, "商品名称": "工业拉手", "图片文件名": pic,
                           "尺寸图文件名": drawing, "型号": sku,
                           "孔距(mm)": hole, "总长(mm)": length,
                           "材质": "", "表面处理": "", "色块颜色": color,
                           "标题字色": "#FFFFFF"})


class QualityGateV7Tests(unittest.TestCase):
    @patch("ecom_images.sku_preflight_v6.read_sku_rows")
    def test_v2_drawing_is_blocked(self, mocked):
        mocked.return_value = [row(2, "LS001", drawing="drawing.png")]
        report = inspect_batch(b"fixture", [photo(), photo("drawing.png")])
        self.assertEqual(report.blocked, 1)
        self.assertIn("V2经典", report.rows[0]["原因"])

    @patch("ecom_images.sku_batch.read_sku_rows")
    def test_v2_drawing_not_silently_ignored_by_renderer(self, mocked):
        mocked.return_value = [row(2, "LS001", drawing="drawing.png")]
        result = build_sku_batch(b"fixture", [photo(), photo("drawing.png")])
        self.assertEqual(result.successes, 0)
        self.assertIn("V2经典", result.rows[0]["message"])

    @patch("ecom_images.sku_preflight_v6.read_sku_rows")
    def test_transparent_image_is_not_ready(self, mocked):
        mocked.return_value = [row(2, "LS001")]
        report = inspect_batch(b"fixture", [photo(transparent=True)])
        self.assertEqual(report.blocked, 1)
        self.assertIn("全透明", report.rows[0]["原因"])

    @patch("ecom_images.sku_preflight_v6.read_sku_rows")
    def test_invalid_dimension_or_color_is_blocked(self, mocked):
        mocked.return_value = [row(2, "LS001", hole="abc"), row(3,"LS002", color="yellow")]
        report = inspect_batch(b"fixture", [photo()])
        self.assertEqual(report.blocked, 2)

    @patch("ecom_images.sku_batch.read_sku_rows")
    def test_partial_batch_only_processes_preflight_approved_row(self, mocked):
        mocked.return_value = [row(2, "LS001"), row(3, "LS002")]
        result = build_sku_batch(b"fixture", [photo()], allowed_row_numbers=frozenset({2}))
        self.assertEqual((result.successes, result.failures), (1, 1))
        self.assertIn("预检查未通过", result.rows[1]["message"])
        self.assertEqual(len(result.images), 1)

    @patch("ecom_images.sku_batch.read_sku_rows")
    def test_empty_allowed_set_never_generates(self, mocked):
        mocked.return_value = [row(2, "LS001")]
        result = build_sku_batch(b"fixture", [photo()], allowed_row_numbers=frozenset())
        self.assertEqual((result.successes, result.failures), (0, 1))

    @patch("ecom_images.sku_batch.read_sku_rows")
    def test_no_allowlist_preserves_existing_cli_workflow(self, mocked):
        mocked.return_value = [row(2, "LS001")]
        result = build_sku_batch(b"fixture", [photo()])
        self.assertEqual(result.successes, 1)

    def test_csv_formula_tab_prefix_is_escaped(self):
        self.assertTrue(_csv_safe("\t=1+1").startswith("'"))
        self.assertTrue(_csv_safe("\r=SUM(1)").startswith("'"))

    def test_ai_cache_binds_photo_and_prompt(self):
        ref = photo()
        args = dict(platform="淘宝 / 天猫", prompt="A", ratio="1:1", resolution="2k", quantity=1, model="demo")
        a = ai_request_fingerprint(ref, **args)
        self.assertEqual(valid_cached_ai_result((a, b"zip"), a), b"zip")
        self.assertIsNone(valid_cached_ai_result((a,b"zip"), ai_request_fingerprint(ref, **{**args,"prompt":"B"})))
        self.assertIsNone(valid_cached_ai_result((a,b"zip"), ai_request_fingerprint(photo("other.png"), **args)))
        self.assertIsNone(valid_cached_ai_result((a,b"zip"), ai_request_fingerprint(None, **args)))

    def test_ai_cache_rejects_malformed_entry(self):
        self.assertIsNone(valid_cached_ai_result(("abc", "not bytes"), "abc"))
        self.assertIsNone(valid_cached_ai_result(b"zip", "abc"))

    def test_template_library_case_insensitive_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            save_template(tmp, "LS-模板", default_layout())
            save_template(tmp, "ls-模板", default_layout(), overwrite=True)
            self.assertEqual(len(list_templates(tmp)), 1)

    def test_template_library_prevents_case_collision_without_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            save_template(tmp, "ABC", default_layout())
            with self.assertRaisesRegex(ValueError, "已存在"):
                save_template(tmp, "abc", default_layout())


if __name__ == "__main__":
    unittest.main()
