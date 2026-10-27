"""Excel SKU 自动制图单元测试：不依赖联网与第三方 Excel 包。"""
import io
import json
import sys
import unittest
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from ecom_images.sku_batch import (COLUMNS, MAX_ROWS, _dimension, build_sku_batch,
                                   read_sku_rows, unpack_image_zip)
from ecom_images.workflow import UploadedPicture


def fake_xlsx(rows, columns=COLUMNS, sheet_name="SKU清单", with_formula=False):
    """可读的最简 OOXML；不会向项目引入运行时 Excel 依赖。"""
    def cell(addr, value, formula=False):
        node = ET.Element("c", {"r": addr, "t": "inlineStr"})
        if formula:
            ET.SubElement(node, "f").text = "1+1"
        is_element = ET.SubElement(node, "is")
        ET.SubElement(is_element, "t").text = str(value)
        return node
    sheet = ET.Element("worksheet", {"xmlns": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"})
    data = ET.SubElement(sheet, "sheetData")
    for rowno, values in enumerate([columns, *rows], start=1):
        row = ET.SubElement(data, "row", {"r": str(rowno)})
        for index, value in enumerate(values):
            if value is None:
                continue
            column = chr(ord("A") + index)
            row.append(cell(f"{column}{rowno}", value, with_formula and rowno == 2 and index == 0))
    wb = f'<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="{sheet_name}" sheetId="1" r:id="rId1"/></sheets></workbook>'
    rels = '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>'
    mem = io.BytesIO()
    with zipfile.ZipFile(mem, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr("xl/workbook.xml", wb)
        z.writestr("xl/_rels/workbook.xml.rels", rels)
        z.writestr("xl/worksheets/sheet1.xml", ET.tostring(sheet, encoding="utf-8", xml_declaration=True))
    return mem.getvalue()


def basic_row(sku="SKU-01", photo="handle.png", hole="200", length="228", color="#F5C518"):
    return [sku, "工业拉手", photo, "拉手型号", hole, length, "不锈钢", "拉丝", color, "#000000"]


def picture(name="handle.png"):
    img = Image.new("RGBA", (350, 350), (0, 0, 0, 0))
    ImageDraw.Draw(img).ellipse((80, 110, 270, 250), fill=(135, 135, 140, 255))
    raw = io.BytesIO()
    img.save(raw, "PNG")
    return UploadedPicture(name, raw.getvalue())


class ExcelSkuTests(unittest.TestCase):
    def test_import_text_and_numbers(self):
        rows = read_sku_rows(fake_xlsx([basic_row(sku="001", hole="250", length="278")]))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].data["SKU编码"], "001")
        self.assertEqual(rows[0].data["孔距(mm)"], "250")

    def test_skip_empty_rows(self):
        self.assertEqual(len(read_sku_rows(fake_xlsx([basic_row(), [None] * 10, basic_row("SKU-02")] ))), 2)

    def test_bad_sheet_and_headers(self):
        with self.assertRaisesRegex(ValueError, "SKU清单"):
            read_sku_rows(fake_xlsx([basic_row()], sheet_name="Bad"))
        with self.assertRaisesRegex(ValueError, "必填列"):
            read_sku_rows(fake_xlsx([basic_row()], columns=["ABC", *COLUMNS[1:]]))

    def test_empty_and_limit(self):
        with self.assertRaisesRegex(ValueError, "没有数据"):
            read_sku_rows(fake_xlsx([]))
        with self.assertRaisesRegex(ValueError, "最多导入"):
            read_sku_rows(fake_xlsx([basic_row(f"SKU-{n}") for n in range(MAX_ROWS + 1)]))

    def test_formula_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "公式"):
            read_sku_rows(fake_xlsx([basic_row()], with_formula=True))

    def test_fake_xlsx_corruption(self):
        with self.assertRaisesRegex(ValueError, "有效"):
            read_sku_rows(b"garbage")

    def test_valid_batch_and_reports(self):
        result = build_sku_batch(fake_xlsx([basic_row()]), [picture()])
        self.assertEqual((result.successes, result.failures), (1, 0))
        self.assertEqual(len(result.images), 1)
        name, data, meta = result.images[0]
        self.assertIn("SKU-01", name)
        self.assertEqual(meta["specs"][1]["value"], "200 mm")
        with Image.open(io.BytesIO(data)) as im:
            self.assertEqual(im.size, (1440, 1440))
        with zipfile.ZipFile(io.BytesIO(result.zip_bytes())) as zf:
            self.assertIn("quality_report.json", zf.namelist())
            self.assertIn("sku_import_report.csv", zf.namelist())
            self.assertIn("sku_import_report.json", zf.namelist())
            self.assertTrue(zf.read("sku_import_report.csv").startswith(b"\xef\xbb\xbf"))
            audit = json.loads(zf.read("quality_report.json"))
            self.assertEqual(audit["summary"]["manual_review_pending"], 1)

    def test_partial_errors_and_duplicate_sku(self):
        rows = [basic_row(), basic_row("SKU-02", "missing.png"), basic_row("SKU-01")]
        result = build_sku_batch(fake_xlsx(rows), [picture()])
        self.assertEqual((result.successes, result.failures), (1, 2))
        self.assertIn("找不到", result.rows[1]["message"])
        self.assertIn("重复", result.rows[2]["message"])

    def test_numeric_check(self):
        for invalid in ("200mm", "1+1", "0", "-1", "1e10", "100001"):
            with self.subTest(value=invalid), self.assertRaises(ValueError):
                _dimension(invalid, "孔距(mm)")
        self.assertEqual(_dimension("228.5", "总长(mm)"), "228.5")

    def test_bad_dimensions_only_fail_own_row(self):
        result = build_sku_batch(fake_xlsx([basic_row("Bad", hole="200mm"), basic_row("Good")]), [picture()])
        self.assertEqual((result.successes, result.failures), (1, 1))
        self.assertIn("不含单位", result.rows[0]["message"])

    def test_exact_image_and_bad_color(self):
        result = build_sku_batch(fake_xlsx([basic_row(photo="folder/handle.png"), basic_row("B", color="not-color")]), [picture()])
        self.assertEqual(result.failures, 2)
        self.assertIn("路径", result.rows[0]["message"])
        self.assertIn("颜色", result.rows[1]["message"])

    def test_zip_image_names(self):
        zipped = io.BytesIO()
        with zipfile.ZipFile(zipped, "w") as z:
            z.writestr("folder/handle.png", picture().data)
        self.assertEqual(unpack_image_zip(zipped.getvalue())[0].name, "handle.png")
        zipped = io.BytesIO()
        with zipfile.ZipFile(zipped, "w") as z:
            z.writestr("a/handle.png", picture().data)
            z.writestr("b/HANDLE.PNG", picture().data)
        with self.assertRaisesRegex(ValueError, "重名"):
            unpack_image_zip(zipped.getvalue())

    def test_csv_formula_escape(self):
        result = build_sku_batch(fake_xlsx([basic_row("=2+3")]), [picture()])
        with zipfile.ZipFile(io.BytesIO(result.zip_bytes())) as z:
            csv_content = z.read("sku_import_report.csv").decode("utf-8-sig")
        self.assertIn("'=2+3", csv_content)

    def test_real_blank_template_present(self):
        path = Path(__file__).resolve().parents[1] / "assets/templates/sku_import_template.xlsx"
        self.assertTrue(path.exists())
        with self.assertRaisesRegex(ValueError, "没有数据"):
            read_sku_rows(path.read_bytes())


if __name__ == "__main__":
    unittest.main()
