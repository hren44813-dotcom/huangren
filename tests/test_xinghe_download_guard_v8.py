"""No-network tests for strict image download safety in the Xinghe skill."""
import importlib.util
import io
import socket
import sys
import unittest
import urllib.request
from pathlib import Path
from unittest.mock import patch

SCRIPT_DIR = Path(__file__).resolve().parents[1] / '.agents/skills/xinghe-crossborder-detail-3/scripts'
sys.path.insert(0, str(SCRIPT_DIR))
from download_guard import (MAX_IMAGE_BYTES, ValidatedRedirects,
                            public_https_image_url, download_image_url, decode_image_base64)

PUBLIC_DNS = [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('93.184.216.34', 443))]
LOCAL_DNS = [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('127.0.0.1', 443))]


class StubResponse:
    def __init__(self, content, url='https://images.example.com/example.png', content_length=None):
        self.content, self.url = content, url
        self.headers = {} if content_length is None else {'Content-Length': str(content_length)}

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass

    def geturl(self):
        return self.url

    def read(self, length):
        return self.content[:length]


class FakeOpener:
    def __init__(self, response):
        self.response = response

    def open(self, req, timeout):
        return self.response


class SafetyTests(unittest.TestCase):
    def test_denies_local_urls_and_non_https(self):
        for value in ('http://images.example.com/foo.png', 'file:///etc/passwd',
                      'https://localhost/a', 'https://127.0.0.1/a',
                      'https://[::1]/a', 'https://10.0.0.1/a',
                      'https://169.254.169.254/metadata', 'https://a.local/x',
                      'https://user:pass@images.example.com/a',
                      'https://images.example.com:8080/a'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                public_https_image_url(value)

    @patch('download_guard.socket.getaddrinfo', return_value=LOCAL_DNS)
    def test_blocks_hostname_resolving_to_loopback(self, dns):
        with self.assertRaisesRegex(ValueError, '非公网'):
            public_https_image_url('https://images.example.com/file.png')

    @patch('download_guard.socket.getaddrinfo', return_value=PUBLIC_DNS)
    def test_permits_public_https_and_checks_redirect(self, dns):
        self.assertEqual(public_https_image_url('https://images.example.com/file.png'),
                         'https://images.example.com/file.png')
        with self.assertRaises(ValueError):
            ValidatedRedirects().redirect_request(None, None, 302, 'Redirect', {}, 'http://127.0.0.1/')

    @patch('download_guard.socket.getaddrinfo', return_value=PUBLIC_DNS)
    def test_rejects_oversized_download_even_when_server_lies(self, dns):
        for content, header in [(b'1' * (MAX_IMAGE_BYTES+1), None), (b'abc', MAX_IMAGE_BYTES+1)]:
            with self.subTest(header=header), patch('download_guard.urllib.request.build_opener',
                                                    return_value=FakeOpener(StubResponse(content, content_length=header))):
                with self.assertRaisesRegex(ValueError, '超过12MB'):
                    download_image_url('https://images.example.com/a.png')

    @patch('download_guard.socket.getaddrinfo', return_value=PUBLIC_DNS)
    def test_final_url_is_validated_after_download(self, dns):
        with patch('download_guard.urllib.request.build_opener',
                   return_value=FakeOpener(StubResponse(b'abc', url='https://localhost/secret'))):
            with self.assertRaises(ValueError):
                download_image_url('https://images.example.com/a.png')

    @patch('download_guard.socket.getaddrinfo', return_value=PUBLIC_DNS)
    def test_valid_small_download(self, dns):
        with patch('download_guard.urllib.request.build_opener',
                   return_value=FakeOpener(StubResponse(b'data'))):
            self.assertEqual(download_image_url('https://images.example.com/a.png'), b'data')

    def test_rejects_invalid_or_oversized_base64(self):
        with self.assertRaisesRegex(ValueError, 'base64'):
            decode_image_base64('@@garbage@@')
        with self.assertRaisesRegex(ValueError, '超过'):
            decode_image_base64('A' * (MAX_IMAGE_BYTES * 2))
        self.assertEqual(decode_image_base64('YWJj'), b'abc')


if __name__ == '__main__':
    unittest.main()
