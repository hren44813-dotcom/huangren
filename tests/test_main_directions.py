import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from ecom_images.main_directions import ProductBrief, plan_directions


class DirectionTests(unittest.TestCase):
    def test_missing_name(self):
        with self.assertRaisesRegex(ValueError, "商品名称"):
            plan_directions(ProductBrief(""))

    def test_three_directions_and_missing_facts(self):
        info, ideas = plan_directions(ProductBrief("MS705"))
        self.assertEqual(len(ideas), 3)
        self.assertEqual([x.key for x in ideas], ["appearance", "spec", "scene"])
        self.assertIn("未提供", info["已确认规格"])
        self.assertNotIn("72小时", repr(ideas))
        self.assertNotIn("304", repr(ideas))

    def test_only_verified_facts(self):
        info, ideas = plan_directions(ProductBrief("LS606", confirmed_spec="孔距 200mm",
                                                   confirmed_scene="设备箱体"))
        self.assertIn("200mm", ideas[1].headline)
        self.assertIn("设备箱体", ideas[2].headline)
        self.assertFalse(any("\n" in x.headline for x in ideas))


if __name__ == "__main__":
    unittest.main()
