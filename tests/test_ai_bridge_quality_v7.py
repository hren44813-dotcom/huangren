"""星河 API 本地替身测试：不访问网络、不产生费用。"""
import io
import sys
import subprocess
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from ecom_images.ai_bridge import generate_xinghe
from ecom_images.workflow import UploadedPicture


def png_image() -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (160, 120), (120, 145, 160)).save(out, format="PNG")
    return out.getvalue()


class AiBridgeQualityV7(unittest.TestCase):
    def execute(self, generated):
        def fake_run(command, cwd, **kwargs):
            folder = Path(cwd) / "generated"
            folder.mkdir()
            for idx, payload in enumerate(generated):
                (folder / f"image_{idx}.png").write_bytes(payload)
            return subprocess.CompletedProcess(command, 0, stdout="ok", stderr="")
        with patch("ecom_images.ai_bridge.subprocess.run", side_effect=fake_run):
            return generate_xinghe(UploadedPicture("product.png", png_image()),
                                   api_key="local-test-only", model="mock", prompt="safe test",
                                   quantity=1, consent=True)

    def test_valid_mock_image_can_be_exported(self):
        result = self.execute([png_image()])
        with zipfile.ZipFile(io.BytesIO(result)) as z:
            self.assertEqual(z.namelist(), ["xinghe_01.png"])

    def test_provider_jpeg_saved_with_correct_extension(self):
        image = io.BytesIO()
        Image.new("RGB", (160, 120), "white").save(image, format="JPEG")
        # Fake provider writes it with a PNG filename; output must match bytes.
        result = self.execute([image.getvalue()])
        with zipfile.ZipFile(io.BytesIO(result)) as z:
            self.assertEqual(z.namelist(), ["xinghe_01.jpg"])

    def test_corrupt_provider_image_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "不合格"):
            self.execute([b"not a png"])

    def test_provider_images_exceed_request_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "超过请求数量"):
            self.execute([png_image(), png_image()])

    def test_without_consent_does_not_call_provider(self):
        with patch("ecom_images.ai_bridge.subprocess.run") as call:
            with self.assertRaisesRegex(ValueError, "必须确认"):
                generate_xinghe(UploadedPicture("product.png", png_image()), api_key="test",
                               model="demo", prompt="test", consent=False)
            call.assert_not_called()


if __name__ == "__main__":
    unittest.main()
