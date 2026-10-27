import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from ecom_images.sku_layout_v4 import default_layout
from ecom_images.template_library_v5 import (
    delete_template, list_templates, load_template, save_template, template_name,
)


class LibraryV5Tests(unittest.TestCase):
    def test_save_load_list_delete(self):
        with tempfile.TemporaryDirectory() as td:
            layout = default_layout()
            self.assertEqual(save_template(td, 'LS拉手-蓝白', layout), 'LS拉手-蓝白')
            self.assertEqual(list_templates(td), ['LS拉手-蓝白'])
            self.assertEqual(load_template(td, 'LS拉手-蓝白'), layout)
            delete_template(td, 'LS拉手-蓝白')
            self.assertEqual(list_templates(td), [])

    def test_no_overwrite_unless_confirmed(self):
        with tempfile.TemporaryDirectory() as td:
            layout = default_layout()
            save_template(td, 'blue', layout)
            with self.assertRaisesRegex(ValueError, '已存在'):
                save_template(td, 'blue', default_layout('黄黑工业风'))
            save_template(td, 'blue', default_layout('黄黑工业风'), overwrite=True)
            self.assertEqual(load_template(td, 'blue')['style'], '黄黑工业风')

    def test_bad_layout_cannot_destroy_saved(self):
        with tempfile.TemporaryDirectory() as td:
            layout = default_layout()
            save_template(td, 'safe', layout)
            bad = default_layout()
            bad['slots']['title'] = [1, 1, 1000, 100]
            with self.assertRaises(ValueError):
                save_template(td, 'safe', bad, overwrite=True)
            self.assertEqual(load_template(td, 'safe'), layout)

    def test_traversal_and_bad_names(self):
        with tempfile.TemporaryDirectory() as td:
            for name in ('../steal', '/tmp/name', 'abc\\x', 'x.json', '', 'a'*49):
                with self.subTest(name=name):
                    with self.assertRaises(ValueError):
                        save_template(td, name, default_layout())

    def test_symlink_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            outside = root / 'outside.json'
            outside.write_text('private')
            lib = root / 'lib'
            lib.mkdir()
            (lib / 'example.json').symlink_to(outside)
            with self.assertRaisesRegex(ValueError, '符号链接'):
                load_template(lib, 'example')
            with self.assertRaisesRegex(ValueError, '符号链接'):
                save_template(lib, 'example', default_layout(), overwrite=True)
            self.assertEqual(outside.read_text(), 'private')

    def test_only_valid_name(self):
        self.assertEqual(template_name('  清爽蓝白  '), '清爽蓝白')


if __name__ == '__main__':
    unittest.main()
