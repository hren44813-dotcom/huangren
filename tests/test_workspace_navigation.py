"""Regression checks for the simplified three-workspace Streamlit navigation."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class WorkspaceNavigationTests(unittest.TestCase):
    def test_three_workspaces_cover_all_eight_existing_functions(self):
        app = (ROOT / "app.py").read_text(encoding="utf-8")
        for name in ("素材制作", "产品资料", "竞品监测"):
            self.assertIn(f'"{name}"', app)
        for feature in (
            "主图方向策划", "标准主图 / SKU 批量制作",
            "Excel SKU / V6 制图审核流程", "星河 AI 详情页（可选）",
            "数据库运营查询（只读）", "商品 / SKU 档案",
            "参数证据审核", "竞品 SKU 每日监测",
        ):
            self.assertIn(f'"{feature}"', app)
        self.assertIn('st.radio("选择工作区"', app)
        self.assertIn('st.selectbox("当前功能"', app)
        self.assertNotIn("st.tabs(", app)

    def test_each_function_is_conditionally_rendered(self):
        app = (ROOT / "app.py").read_text(encoding="utf-8")
        self.assertEqual(app.count('if page == "'), 8)
        for module in (
            "render_main_directions(st, platform)",
            "render_sku_batch(st, platform)",
            "render_db_reporting(st)",
            "render_catalog_v12(st)",
            "render_knowledge_review(st)",
            "render_competitor_monitor(st)",
        ):
            self.assertIn(module, app)
        self.assertIn("generate_xinghe(", app)
        self.assertIn("produce_images(", app)


if __name__ == "__main__":
    unittest.main()
