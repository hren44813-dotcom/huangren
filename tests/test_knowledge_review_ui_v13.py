"""Regression checks that the V13 review workflow is mounted in the Streamlit app."""
import sys
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
from ecom_images.knowledge_review_ui_v13 import render

class KnowledgeReviewUIWiringTests(unittest.TestCase):
    def test_streamlit_app_mounts_the_review_workspace(self):
        app=(ROOT/"app.py").read_text(encoding="utf-8")
        module=ROOT/"src/ecom_images/knowledge_review_ui_v13.py"
        self.assertTrue(module.is_file(),"the review UI module must exist")
        self.assertTrue(callable(render))
        self.assertIn("from ecom_images.knowledge_review_ui_v13 import render as render_knowledge_review",app)
        self.assertIn("⑦ 参数证据审核",app)
        self.assertIn("with knowledge_tab:",app)
        self.assertIn("render_knowledge_review(st)",app)
        ui=(ROOT/"src/ecom_images/knowledge_review_ui_v13.py").read_text(encoding="utf-8")
        self.assertIn("导入原始资料",ui)
        self.assertIn("st.file_uploader",ui)
        self.assertIn("import_document(",ui)

if __name__=="__main__": unittest.main(verbosity=2)
