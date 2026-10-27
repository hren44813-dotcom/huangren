"""Guard image URLs returned by third-party model services.

Controls are defense-in-depth, not an absolute defense against DNS rebinding. The
external image endpoint must only be used in a trusted, isolated environment.
"""
from __future__ import annotations

import base64
import binascii
import ipaddress
import socket
import urllib.error
import urllib.parse
import urllib.request

MAX_IMAGE_BYTES = 12 * 1024 * 1024
MAX_BASE64_CHARS = (MAX_IMAGE_BYTES * 4 // 3) + 16


def public_https_image_url(url: str) -> str:
    """Refuse non-HTTPS, local addresses, DNS destinations with private IPs."""
    if not isinstance(url, str) or not url or len(url) > 4096 or any(ord(ch) < 33 for ch in url):
        raise ValueError("图片 URL 缺失、过长或包含不可用字符")
    try:
        parsed = urllib.parse.urlsplit(url)
        host = parsed.hostname
        port = parsed.port
    except ValueError as exc:
        raise ValueError("图片 URL 结构无效") from exc
    if parsed.scheme.lower() != "https" or not host or parsed.username or parsed.password or port not in (None, 443):
        raise ValueError("仅允许未携带账户信息的标准 HTTPS 图片地址")
    if parsed.fragment:
        raise ValueError("图片 URL 不允许片段")
    name = host.rstrip('.').lower()
    if not name or name == 'localhost' or '.' not in name or name.endswith((
        '.localhost', '.local', '.internal', '.lan', '.test', '.invalid', '.onion', '.home.arpa',
    )):
        raise ValueError("不能从本机或内部域名下载图片")
    try:
        ip = ipaddress.ip_address(name)
    except ValueError:
        try:
            ips = {ipaddress.ip_address(result[4][0]) for result in socket.getaddrinfo(
                name, 443, type=socket.SOCK_STREAM,
            )}
        except (OSError, ValueError) as exc:
            raise ValueError("图片域名 DNS 解析失败") from exc
        if not ips or any(not addr.is_global for addr in ips):
            raise ValueError("图片域名解析到非公网地址")
    else:
        if not ip.is_global:
            raise ValueError("不能从非公网 IP 下载图片")
    return url


class ValidatedRedirects(urllib.request.HTTPRedirectHandler):
    """All HTTP redirects must also pass the public HTTPS check."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        public_https_image_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def download_image_url(url: str, *, timeout: int = 45) -> bytes:
    """Download with HTTPS/redirect checks and a hard response size bound.

    Environment-configured proxies are disabled for returned image URLs.
    """
    public_https_image_url(url)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), ValidatedRedirects())
    request = urllib.request.Request(url, headers={"User-Agent": "huangren-image-client"})
    with opener.open(request, timeout=timeout) as response:
        final_url = response.geturl()
        public_https_image_url(final_url)
        advertised = response.headers.get('Content-Length')
        if advertised is not None:
            try:
                declared_size = int(advertised)
            except (TypeError, ValueError) as exc:
                raise ValueError("图片长度响应头无效") from exc
            if declared_size < 0:
                raise ValueError("图片长度响应头无效")
            if declared_size > MAX_IMAGE_BYTES:
                raise ValueError("图片下载超过12MB")
        data = response.read(MAX_IMAGE_BYTES + 1)
        if not data or len(data) > MAX_IMAGE_BYTES:
            raise ValueError("图片为空或下载超过12MB")
        return data


def decode_image_base64(value: str) -> bytes:
    """Decode base64 without allocating unbounded buffers."""
    if not isinstance(value, str) or not value or len(value) > MAX_BASE64_CHARS:
        raise ValueError("base64 图片为空或超过12MB上限")
    try:
        result = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("图片 base64 内容不合法") from exc
    if not result or len(result) > MAX_IMAGE_BYTES:
        raise ValueError("图片 base64 内容为空或超过12MB上限")
    return result
