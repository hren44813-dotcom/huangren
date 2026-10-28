"""Offline test coverage for daily multi-SKU competitor monitoring and truthful price reports."""
from __future__ import annotations

import csv
import io
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ecom_images.competitor_monitor import (
    FIELDS, available_dates, daily_report, import_csv, parse_csv,
    report_csv, template_csv,
)

URL = "https://detail.tmall.com/item.htm?id=12345"
URL2 = "https://item.taobao.com/item.htm?id=7890"


def sample(**change):
    row = {
        "日期": "2026-10-28", "竞店": "示例工业五金店", "竞品链接": URL,
        "SKU": "MS705-锌合金", "SKU价格": "12.50", "币种": "CNY",
        "链接销量": "30", "评价带图": "有", "优惠券": "无",
        "活动": "未显示", "截图文件名": "20261028_MS705.png", "备注": "",
    }
    row.update(change)
    return row


def csv_bytes(*rows):
    out = io.StringIO(newline="")
    writer = csv.DictWriter(out, fieldnames=FIELDS)
    writer.writeheader()
    writer.writerows(rows)
    return ("\ufeff" + out.getvalue()).encode("utf-8")


class CompetitorMonitoringTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Path(self.tmp.name) / ".local" / "competitor.sqlite3"

    def test_template_and_preview_are_safe_without_creating_db(self):
        header = template_csv().decode("utf-8-sig").splitlines()[0]
        self.assertEqual(header.split(","), list(FIELDS))
        raw = csv_bytes(sample())
        self.assertEqual(parse_csv(raw)[0]["price_cents"], 1250)
        preview = import_csv(self.db, raw, dry_run=True)
        self.assertEqual(preview["new"], 1)
        self.assertTrue(preview["dry_run"])
        self.assertFalse(self.db.exists())
        self.assertEqual(available_dates(self.db), [])
        with self.assertRaisesRegex(ValueError, "尚未导入"):
            daily_report(self.db, "2026-10-28")
        self.assertFalse(self.db.exists())

    def test_multi_sku_link_price_history_and_missing_sku_warning(self):
        first = csv_bytes(
            sample(SKU="MS705-锌合金", SKU价格="12.50"),
            sample(SKU="MS705-304不锈钢", SKU价格="25.00"),
        )
        added = import_csv(self.db, first, dry_run=False)
        self.assertEqual(added["rows"], 2)
        self.assertEqual(added["links"], 1)
        self.assertEqual(available_dates(self.db), ["2026-10-28"])
        first_report = daily_report(self.db, "2026-10-28")
        self.assertEqual(first_report["new_skus"], 2)
        self.assertFalse(first_report["missing"])

        second = csv_bytes(
            sample(日期="2026-10-30", SKU="MS705-锌合金", SKU价格="11.80",
                   链接销量="35", 评价带图="无", 优惠券="有"),
            sample(日期="2026-10-30", SKU="MS705-新增黑色", SKU价格="13.20",
                   链接销量="35", 评价带图="无", 优惠券="有"),
        )
        import_csv(self.db, second, dry_run=False)
        report = daily_report(self.db, "2026-10-30")
        self.assertEqual((report["total"], report["price_down"], report["new_skus"]), (2, 1, 1))
        by_sku = {row["SKU"]: row for row in report["rows"]}
        old = by_sku["MS705-锌合金"]
        self.assertEqual(old["前次日期"], "2026-10-28")
        self.assertEqual(old["前次价格"], "12.50")
        self.assertEqual(old["本次价格"], "11.80")
        self.assertEqual(old["变动金额"], "-0.70")
        self.assertEqual(old["价格变化"], "降价")
        self.assertEqual(old["链接销量"], 35)
        self.assertEqual(report["missing"], [{
            "竞品链接": URL, "SKU": "MS705-304不锈钢",
            "前次日期": "2026-10-28", "状态": "本次未记录（不能认定下架）",
        }])
        result_csv = report_csv(report)
        self.assertTrue(result_csv.startswith(b"\xef\xbb\xbf"))
        self.assertEqual(len(list(csv.DictReader(io.StringIO(result_csv.decode("utf-8-sig"))))), 2)

    def test_identical_reimport_is_idempotent_and_conflict_rolls_back(self):
        raw = csv_bytes(sample())
        import_csv(self.db, raw, dry_run=False)
        self.assertEqual(import_csv(self.db, raw, dry_run=True)["unchanged"], 1)
        self.assertEqual(import_csv(self.db, raw, dry_run=False)["unchanged"], 1)
        different = csv_bytes(
            sample(竞品链接=URL2, SKU="CL226", SKU价格="9.90"),
            sample(SKU价格="1.00"),
        )
        with self.assertRaisesRegex(ValueError, "已存在不同数据"):
            import_csv(self.db, different, dry_run=False)
        with sqlite3.connect(self.db) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM competitor_observations").fetchone()[0], 1)
            with self.assertRaises(sqlite3.DatabaseError):
                conn.execute("UPDATE competitor_observations SET price_cents=5")
            with self.assertRaises(sqlite3.DatabaseError):
                conn.execute("DELETE FROM competitor_observations")
        self.assertEqual(import_csv(self.db, raw, dry_run=False)["new"], 0)

    def test_unknown_prices_or_currency_mismatch_never_become_fake_price_changes(self):
        import_csv(self.db, csv_bytes(sample(SKU价格="", 链接销量="")), dry_run=False)
        import_csv(self.db, csv_bytes(sample(日期="2026-10-29", SKU价格="3.40", 链接销量="")), dry_run=False)
        a = daily_report(self.db, "2026-10-29")["rows"][0]
        self.assertEqual(a["价格变化"], "无法比较")
        self.assertEqual(a["前次价格"], "")
        self.assertIsNone(a["链接销量"])
        self.assertEqual(a["变动金额"], "")
        import_csv(self.db, csv_bytes(sample(日期="2026-10-30", SKU价格="4.00", 币种="USD")), dry_run=False)
        b = daily_report(self.db, "2026-10-30")["rows"][0]
        self.assertEqual(b["价格变化"], "无法比较")

    def test_bad_input_rejected_before_database_creation(self):
        bads = [
            sample(日期="2026/10/28"),
            sample(日期="2026-02-30"),
            sample(竞品链接="http://localhost/product/1"),
            sample(竞品链接="https://127.0.0.1/product/1"),
            sample(竞品链接="https://evil.example@localhost/product/1"),
            sample(竞品链接="https://item.taobao.com:444/item"),
            sample(SKU价格="12-14"),
            sample(SKU价格="-1"),
            sample(链接销量="-1"),
            sample(评价带图="是"),
            sample(优惠券=""),
            sample(截图文件名="../private.png"),
            sample(SKU="=HYPERLINK(123)"),
            sample(备注="@SUM(1)"),
            sample(币种="元"),
        ]
        for row in bads:
            with self.subTest(bad=row):
                with self.assertRaises(ValueError):
                    import_csv(self.db, csv_bytes(row), dry_run=False)
                self.assertFalse(self.db.exists())

    def test_duplicate_rows_and_link_level_contradictions_rejected(self):
        with self.assertRaisesRegex(ValueError, "重复"):
            parse_csv(csv_bytes(sample(), sample()))
        with self.assertRaisesRegex(ValueError, "不一致"):
            parse_csv(csv_bytes(sample(), sample(SKU="MS705-304", 优惠券="有")))
        with self.assertRaises(ValueError):
            parse_csv(csv_bytes(sample())[:20])
        with self.assertRaises(ValueError):
            parse_csv(b"\xef\xbb\xbfnot,correct\n1,2\n")
        with self.assertRaises(ValueError):
            parse_csv(b"x" * (2 * 1024 * 1024 + 1))

    def test_newer_day_does_not_reinterpret_earlier_missing_sku_as_delisted(self):
        import_csv(self.db, csv_bytes(sample(), sample(SKU="MS705-304", SKU价格="25.00")), dry_run=False)
        import_csv(self.db, csv_bytes(sample(日期="2026-10-29")), dry_run=False)
        report = daily_report(self.db, "2026-10-29")
        self.assertEqual(report["rows"][0]["价格变化"], "持平")
        self.assertEqual(report["missing"][0]["状态"], "本次未记录（不能认定下架）")

    def test_export_escapes_formula_strings(self):
        fields = ("日期", "竞店", "竞品链接", "SKU", "本次价格", "币种", "前次日期",
                  "前次价格", "价格变化", "变动金额", "链接销量",
                  "评价带图", "优惠券", "活动", "截图文件名", "备注")
        row = {field: "" for field in fields}
        row["备注"] = "=HYPERLINK('bad')"
        row["SKU"] = "+1+2"
        row["变动金额"] = "-0.70"
        content = report_csv({"rows": [row]}).decode("utf-8-sig")
        parsed = list(csv.DictReader(io.StringIO(content)))[0]
        self.assertEqual(parsed["SKU"], "'+1+2")
        self.assertEqual(parsed["备注"], "'=HYPERLINK('bad')")
        self.assertEqual(parsed["变动金额"], "-0.70")

    def test_streamlit_mount_has_guided_workflow(self):
        app = (ROOT / "app.py").read_text(encoding="utf-8")
        self.assertIn('"竞品监测": ["竞品 SKU 每日监测"]', app)
        self.assertIn('if page == "竞品 SKU 每日监测":', app)
        self.assertIn("render_competitor_monitor(st)", app)
        ui = (ROOT / "src/ecom_images/competitor_monitor_ui.py").read_text(encoding="utf-8")
        self.assertIn("预检数据", ui)
        self.assertIn("确认保存历史数据", ui)
        self.assertIn("下载该日变化报表", ui)


if __name__ == "__main__":
    unittest.main()
