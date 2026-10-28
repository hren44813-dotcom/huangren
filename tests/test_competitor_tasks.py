"""End-to-end offline tests for fixed competitor SKU assignments and truthful alerts."""
from __future__ import annotations

import csv
import io
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from ecom_images.competitor_monitor import FIELDS, import_csv
from ecom_images.competitor_tasks import (
    WATCH_FIELDS, daily_blank_csv, daily_checklist, import_watchlist,
    list_watchlist, parse_watchlist, watch_template,
)

URL = "https://item.taobao.com/item.htm?id=1001"


def make_csv(fields, rows):
    out = io.StringIO(newline="")
    writer = csv.DictWriter(out, fieldnames=fields)
    writer.writeheader()
    writer.writerows(rows)
    return ("\ufeff" + out.getvalue()).encode("utf-8")


def watch(sku="MS705-锌合金", **kwargs):
    data = {"竞店": "示例设备五金店", "竞品链接": URL, "SKU": sku, "币种": "CNY",
            "监测状态": "启用"}
    data.update(kwargs)
    return data


def observation(day, sku, price, **kwargs):
    data = {"日期": day, "竞店": "示例设备五金店", "竞品链接": URL,
            "SKU": sku, "SKU价格": price, "币种": "CNY", "链接销量": "30",
            "评价带图": "有", "优惠券": "无", "活动": "未显示",
            "截图文件名": "", "备注": ""}
    data.update(kwargs)
    return data


class CompetitorTasksTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.db = Path(temporary.name) / "competitor.sqlite3"

    def upload_watch(self, *rows, dry_run=False):
        return import_watchlist(self.db, make_csv(WATCH_FIELDS, rows), dry_run=dry_run)

    def upload_daily(self, *rows):
        return import_csv(self.db, make_csv(FIELDS, rows), dry_run=False)

    def test_watch_template_and_preview_do_not_create_database(self):
        self.assertEqual(watch_template().decode("utf-8-sig").splitlines()[0].split(","),
                         list(WATCH_FIELDS))
        result = self.upload_watch(watch(), watch("MS705-304不锈钢"), dry_run=True)
        self.assertEqual(result["new"], 2)
        self.assertFalse(self.db.exists())
        self.assertEqual(list_watchlist(self.db), [])
        report = daily_checklist(self.db, "2026-10-28")
        self.assertEqual(report["total"], 0)
        self.assertFalse(self.db.exists())

    def test_multi_sku_checklist_and_blank_daily_sheet(self):
        self.upload_watch(watch(), watch("MS705-304不锈钢"))
        report = daily_checklist(self.db, "2026-10-28")
        self.assertEqual((report["total"], report["pending"], report["completed"]), (2, 2, 0))
        self.assertEqual({r["状态"] for r in report["rows"]}, {"待监测"})
        sheet = daily_blank_csv(self.db, "2026-10-28")
        rows = list(csv.DictReader(io.StringIO(sheet.decode("utf-8-sig"))))
        self.assertEqual(len(rows), 2)
        for row in rows:
            self.assertEqual(row["日期"], "2026-10-28")
            self.assertEqual(row["SKU价格"], "")
            self.assertEqual(row["链接销量"], "")
            self.assertEqual(row["优惠券"], "")
        self.upload_daily(observation("2026-10-28", "MS705-锌合金", "10.00"))
        progress = daily_checklist(self.db, "2026-10-28")
        self.assertEqual((progress["completed"], progress["pending"]), (1, 1))
        self.assertEqual({r["SKU"] for r in progress["rows"] if r["状态"] == "待监测"},
                         {"MS705-304不锈钢"})

    def test_missing_price_does_not_count_as_completion(self):
        self.upload_watch(watch())
        self.upload_daily(observation("2026-10-28", "MS705-锌合金", ""))
        progress = daily_checklist(self.db, "2026-10-28")
        self.assertEqual((progress["completed"], progress["missing_price"], progress["pending"]),
                         (0, 1, 1))
        self.assertEqual(progress["rows"][0]["状态"], "已记录待补价格")
        self.assertTrue(any(a["类型"] == "缺少价格" for a in progress["alerts"]))

    def test_price_and_coupon_changes_flagged_once_per_link(self):
        self.upload_watch(watch(), watch("MS705-304不锈钢"))
        self.upload_daily(
            observation("2026-10-27", "MS705-锌合金", "10.00", 优惠券="无", 活动="无"),
            observation("2026-10-27", "MS705-304不锈钢", "20.00", 优惠券="无", 活动="无"))
        self.upload_daily(
            observation("2026-10-28", "MS705-锌合金", "7.00", 优惠券="有", 活动="有"),
            observation("2026-10-28", "MS705-304不锈钢", "21.00", 优惠券="有", 活动="有"))
        progress = daily_checklist(self.db, "2026-10-28", alert_percent=20)
        self.assertEqual((progress["completed"], progress["pending"]), (2, 0))
        kinds = [row["类型"] for row in progress["alerts"]]
        self.assertEqual(kinds.count("价格异常变动"), 1)
        self.assertEqual(kinds.count("优惠券变化"), 1)
        self.assertEqual(kinds.count("活动变化"), 1)
        self.assertTrue(any("-30.0%" in row["说明"] for row in progress["alerts"]))

    def test_observation_without_prior_confirmed_coupon_has_no_false_coupon_alert(self):
        self.upload_watch(watch())
        self.upload_daily(observation("2026-10-27", "MS705-锌合金", "10.00", 优惠券="未显示"))
        self.upload_daily(observation("2026-10-28", "MS705-锌合金", "12.00", 优惠券="有"))
        report = daily_checklist(self.db, "2026-10-28", alert_percent=25)
        self.assertFalse(any(a["类型"] == "优惠券变化" for a in report["alerts"]))
        self.assertFalse(any(a["类型"] == "价格异常变动" for a in report["alerts"]))

    def test_disabling_and_reenabling_preserves_history_and_audit(self):
        self.upload_watch(watch(), watch("MS705-304不锈钢"))
        self.upload_daily(observation("2026-10-27", "MS705-304不锈钢", "20.00"))
        disable = self.upload_watch(watch("MS705-304不锈钢", 监测状态="停用"))
        self.assertEqual(disable["updated"], 1)
        self.assertEqual(len(list_watchlist(self.db)), 2)
        self.assertEqual(len(list_watchlist(self.db, active_only=True)), 1)
        self.assertEqual(daily_checklist(self.db, "2026-10-28")["total"], 1)
        enable = self.upload_watch(watch("MS705-304不锈钢"))
        self.assertEqual(enable["updated"], 1)
        self.assertEqual(daily_checklist(self.db, "2026-10-28")["total"], 2)
        self.assertEqual(daily_checklist(self.db, "2026-10-27")["completed"], 1)
        with sqlite3.connect(self.db) as conn:
            events = conn.execute(
                "SELECT old_json,new_json FROM competitor_watchlist_events ORDER BY id").fetchall()
            self.assertEqual(len(events), 4)
            self.assertEqual(json.loads(events[-1][1])["active"], 1)
            with self.assertRaises(sqlite3.DatabaseError):
                conn.execute("DELETE FROM competitor_watchlist_events")

    def test_duplicate_watch_sku_and_link_conflicts_fail_before_writes(self):
        with self.assertRaisesRegex(ValueError, "重复"):
            self.upload_watch(watch(), watch())
        self.assertFalse(self.db.exists())
        with self.assertRaisesRegex(ValueError, "竞店不一致"):
            self.upload_watch(watch(), watch("MS705-304", 竞店="另一店"))
        self.assertFalse(self.db.exists())
        for change in (
            {"竞品链接": "https://localhost/admin"},
            {"监测状态": "已下架"},
            {"SKU": "=BAD()"},
            {"币种": "元"},
        ):
            with self.subTest(change=change):
                with self.assertRaises(ValueError):
                    self.upload_watch(watch(**change))
                self.assertFalse(self.db.exists())

    def test_invalid_task_day_and_threshold_fail_without_changing_history(self):
        self.upload_watch(watch())
        with self.assertRaises(ValueError):
            daily_checklist(self.db, "2026-02-30")
        with self.assertRaises(ValueError):
            daily_checklist(self.db, "2026-10-28", alert_percent=0)
        with self.assertRaises(ValueError):
            daily_checklist(self.db, "2026-10-28", alert_percent=101)
        with sqlite3.connect(self.db) as conn:
            self.assertEqual(conn.execute(
                "SELECT COUNT(*) FROM competitor_watchlist_events").fetchone()[0], 1)

    def test_watch_import_idempotent_preview_and_explicit_update(self):
        original = make_csv(WATCH_FIELDS, [watch()])
        self.assertEqual(import_watchlist(self.db, original, dry_run=False)["new"], 1)
        self.assertEqual(import_watchlist(self.db, original, dry_run=True)["unchanged"], 1)
        self.assertEqual(import_watchlist(self.db, original, dry_run=False)["unchanged"], 1)
        change = make_csv(WATCH_FIELDS, [watch(监测状态="停用")])
        self.assertEqual(import_watchlist(self.db, change, dry_run=True)["updated"], 1)
        self.assertEqual(list_watchlist(self.db)[0]["active"], 1)
        self.assertEqual(import_watchlist(self.db, change, dry_run=False)["updated"], 1)
        self.assertEqual(list_watchlist(self.db)[0]["active"], 0)

    def test_ui_has_watchlist_daily_checklist_and_alerts(self):
        ui = (ROOT / "src/ecom_images/competitor_monitor_ui.py").read_text(encoding="utf-8")
        for phrase in ("下载竞品链接与 SKU 固定清单模板", "预检固定清单",
                       "确认保存固定清单", "下载当天 SKU 监测任务表",
                       "已完成价格记录", "未完成/待补价格", "价格异常变动提醒阈值"):
            self.assertIn(phrase, ui)


if __name__ == "__main__":
    unittest.main()
