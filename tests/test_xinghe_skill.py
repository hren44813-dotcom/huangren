"""Offline checks for installed Xinghe repository skill (never call external API)."""
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / ".agents/skills/xinghe-crossborder-detail-3"

class XingheSkillTests(unittest.TestCase):
    def test_skill_package_structure(self):
        text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("name: xinghe-crossborder-detail-3", text)
        self.assertTrue((SKILL / "agents/openai.yaml").exists())
        self.assertTrue((SKILL / "references/fallback-generation.md").exists())
        self.assertTrue((SKILL / ".env.example").exists())

    def test_script_cli_offline(self):
        for script in ("generate_image.py", "generate_batch.py"):
            with self.subTest(script=script):
                completed = subprocess.run([sys.executable, str(SKILL / "scripts" / script), "--help"],
                                           capture_output=True, text=True, timeout=12)
                self.assertEqual(completed.returncode, 0, completed.stderr)
                self.assertIn("--output-dir", completed.stdout)

    def test_no_key_in_example(self):
        env = (SKILL / ".env.example").read_text(encoding="utf-8")
        self.assertIn("your-api-key", env)
        self.assertFalse((ROOT / ".env").exists())

if __name__ == "__main__":
    unittest.main()
