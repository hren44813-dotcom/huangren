"""Crawl accessible public Alibaba supplier-shop pages into the V13 source index.

This tool stores each fetched HTML page as an immutable V13 source and emits a
page inventory with only literal text candidates. It never fabricates missing
SKU attributes or creates accepted knowledge claims.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
import time
from collections import deque
from datetime import datetime, timezone
from html import unescape
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urldefrag, urljoin, urlsplit, urlunsplit
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from ecom_images.database_v9 import DEFAULT_DB
from ecom_images.knowledge_ingest_v13 import import_document, initialize_ingestion
from ecom_images.html_capture_v13 import parse_html_document

SHOP_HOST = "dgdeler.en.alibaba.com"
DEFAULT_START = f"https://{SHOP_HOST}/"
MAX_BODY_BYTES = 20 * 1024 * 1024
DEFAULT_MAX_PAGES = 500
USER_AGENT = "Mozilla/5.0 (compatible; HuangrenV13CatalogResearch/1.0)"
PRODUCT_PATH = re.compile(r"(?:product-detail|productdetail|product/|/product[-_])", re.I)
LIST_PATH = re.compile(r"(?:productlist|productgrouplist|search|category)", re.I)
CAPTCHA_MARKERS = ("unusual traffic", "slide to verify", "captcha", "verify you are human")
FIELD_PATTERNS = {
    "model_or_sku": re.compile(r"\b(?:model|item\s*(?:no|number)|sku|part\s*(?:no|number))\s*[:：#-]?\s*([A-Z0-9][A-Z0-9._/-]{1,60})", re.I),
    "material": re.compile(r"\b(?:material|body\s*material|finish\s*material)\s*[:：]\s*([^|;\n]{1,100})", re.I),
    "dimensions": re.compile(r"\b(?:dimension|size|overall\s*length|hole\s*distance|mounting\s*hole|cut[- ]?out)\s*[:：]\s*([^|;\n]{1,120})", re.I),
    "moq": re.compile(r"\b(?:minimum\s*order\s*quantity|moq|min\.?\s*order|minimum\s*order)\s*[:：]?\s*([^|;\n]{1,80})", re.I),
    "price": re.compile(r"\b(?:price|unit\s*price|price\s*range)\s*[:：]?\s*([^|;\n]{1,100})", re.I),
    "specification": re.compile(r"\b(?:specification|specifications|torque|load\s*capacity|opening\s*angle|salt\s*spray)\s*[:：]\s*([^|;\n]{1,120})", re.I),
}


def canonical_url(url: str) -> str | None:
    """Normalize a URL and reject off-site or non-HTTP destinations."""
    absolute = urldefrag(url)[0]
    parts = urlsplit(absolute)
    if parts.scheme not in {"http", "https"} or (parts.hostname or "").lower() != SHOP_HOST:
        return None
    if parts.username or parts.password:
        return None
    query = [(key, value) for key, values in parse_qs(parts.query, keep_blank_values=True).items()
             for value in values if not key.lower().startswith("spm") and key.lower() not in {"from", "tracelog"}]
    from urllib.parse import urlencode
    return urlunsplit(("https", SHOP_HOST, parts.path or "/", urlencode(query), ""))


def classify_page(url: str, text: str) -> str:
    """Classify a storefront page without treating a guessed path as a product."""
    path = urlsplit(url).path
    if "company_profile" in path:
        return "company_profile"
    if PRODUCT_PATH.search(path) and not LIST_PATH.search(path):
        return "possible_product_detail"
    if LIST_PATH.search(path) or path in {"/", "/index.html"}:
        return "listing_or_category"
    return "other_store_page"


def extract_literal_candidates(text: str) -> dict[str, str]:
    """Return only values literally present in visible page text."""
    result = {}
    for field, pattern in FIELD_PATTERNS.items():
        match = pattern.search(text)
        if match:
            value = unescape(" ".join(match.group(1).split())).strip(" \t\r\n:：;；,，")
            if value:
                result[field] = value
    return result


def _fetch(url: str, timeout: float) -> tuple[int, str, str]:
    """Fetch a public page with bounded response size and return status, HTML and final URL."""
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"})
    with urlopen(request, timeout=timeout) as response:
        status = int(response.status)
        final_url = response.geturl()
        content_type = response.headers.get("Content-Type", "")
        if "html" not in content_type.lower() and content_type:
            raise ValueError(f"非 HTML 响应：{content_type}")
        body = response.read(MAX_BODY_BYTES + 1)
        if len(body) > MAX_BODY_BYTES:
            raise ValueError(f"网页超过 {MAX_BODY_BYTES} 字节限制")
        charset = response.headers.get_content_charset() or "utf-8"
        return status, body.decode(charset, errors="replace"), final_url


def _is_captcha(html: str) -> bool:
    sample = html[:2_000_000].casefold()
    return any(marker in sample for marker in CAPTCHA_MARKERS)


def crawl(start_url: str, *, seed_urls: list[str] | None = None, max_pages: int = DEFAULT_MAX_PAGES, delay: float = 1.0,
          timeout: float = 20.0, database: Path = DEFAULT_DB, output_dir: Path = Path("artifacts/alibaba-shop-v13"),
          fetcher=_fetch) -> dict:
    """Crawl same-shop category/list/product links and import each accessible HTML snapshot."""
    if not 1 <= max_pages <= 5000:
        raise ValueError("max_pages 必须在 1 到 5000 之间")
    if not 0 <= delay <= 60:
        raise ValueError("delay 必须在 0 到 60 秒之间")
    seed = canonical_url(start_url)
    if not seed:
        raise ValueError(f"起始链接必须属于 {SHOP_HOST}")
    output_dir.mkdir(parents=True, exist_ok=True)
    snapshots = output_dir / "html"
    snapshots.mkdir(parents=True, exist_ok=True)
    initialize_ingestion(database)
    seeds = [seed]
    for candidate in seed_urls or []:
        normalized = canonical_url(candidate)
        if not normalized:
            raise ValueError(f"种子链接必须属于 {SHOP_HOST}：{candidate}")
        if normalized not in seeds:
            seeds.append(normalized)
    queue = deque(seeds)
    queued = set(seeds)
    visited = set()
    pages = []
    errors = []
    blocked = False

    while queue and len(visited) < max_pages:
        url = queue.popleft()
        if url in visited:
            continue
        visited.add(url)
        row = {"url": url, "status": "failed", "page_type": "unknown", "http_status": None,
               "title": "", "filename": "", "sha256": "", "source_id": "", "segment_count": 0,
               "candidates": {}, "missing_fields": list(FIELD_PATTERNS), "outgoing_same_shop_links": 0,
               "note": ""}
        try:
            status, html, final_url = fetcher(url, timeout)
            final = canonical_url(final_url)
            if not final:
                raise ValueError("重定向到店铺外 URL，已拒绝")
            row["http_status"] = status
            if _is_captcha(html):
                row["status"] = "blocked"
                row["note"] = "检测到验证码/反爬页面；未将验证码内容导入产品资料"
                pages.append(row)
                errors.append({"url": url, "reason": row["note"]})
                blocked = True
                # Continue other known seeds so the report distinguishes accessible and blocked sections.
                if delay:
                    time.sleep(delay)
                continue
            parsed = parse_html_document(html, base_url=final)
            text = "\n".join(parsed["lines"])
            row["url"] = final
            row["title"] = parsed.get("title", "")
            row["page_type"] = classify_page(final, text)
            row["candidates"] = extract_literal_candidates(text)
            row["missing_fields"] = [field for field in FIELD_PATTERNS if field not in row["candidates"]]
            filename_hash = hashlib.sha256(final.encode("utf-8")).hexdigest()[:20]
            filename = f"{filename_hash}.html"
            snapshot_path = snapshots / filename
            snapshot_path.write_text(html, encoding="utf-8")
            result = import_document(
                database, file_path=snapshot_path, source_kind="supplier_document",
                authority_level="user_supplied", document_family="Alibaba supplier storefront",
                document_number=final, source_metadata={
                    "source_url": final, "retrieved_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    "page_type": row["page_type"], "capture_method": "public_http_html",
                    "visible_text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                },
            )
            row.update({"status": "imported", "filename": filename, "sha256": result["sha256"],
                        "source_id": result["source_id"], "segment_count": result["segment_count"],
                        "outgoing_same_shop_links": 0, "note": "; ".join(result.get("warnings", []))})
            links = []
            for item in parsed["links"]:
                link = canonical_url(urljoin(final, item["url"]))
                if link and link not in queued and link not in visited:
                    path = urlsplit(link).path
                    # Product/category/list paths and pagination are the primary crawl targets.
                    is_target = (LIST_PATH.search(path) or PRODUCT_PATH.search(path) or
                                 path in {"/", "/index.html", "/company_profile.html"})
                    if is_target:
                        links.append(link)
            # Stable ordering and a conservative same-host boundary; retain all discovered target paths.
            links = sorted(set(links))
            row["outgoing_same_shop_links"] = len(links)
            for link in links:
                if link not in queued and link not in visited:
                    queued.add(link)
                    queue.append(link)
            pages.append(row)
            if delay:
                time.sleep(delay)
        except (HTTPError, URLError, TimeoutError, OSError, UnicodeError, ValueError) as exc:
            row["status"] = "failed"
            row["note"] = f"{type(exc).__name__}: {exc}"
            pages.append(row)
            errors.append({"url": url, "reason": row["note"]})
            if delay:
                time.sleep(delay)

    if queue:
        errors.append({"url": "", "reason": f"达到页面上限 {max_pages}，仍有 {len(queue)} 个待访问 URL"})
    if blocked:
        errors.append({"url": "", "reason": "本次遍历因验证码/反爬中断；需要人工浏览器导出页面 HTML 后离线导入，不能推断未访问商品"})
    report = {
        "shop": f"https://{SHOP_HOST}/", "started_url": seed,
        "retrieved_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "pages_attempted": len(pages), "pages_imported": sum(p["status"] == "imported" for p in pages),
        "pages_failed_or_blocked": sum(p["status"] in {"failed", "blocked"} for p in pages),
        "product_detail_candidates": sum(p["page_type"] == "possible_product_detail" for p in pages),
        "captcha_blocked": blocked, "remaining_queue": len(queue),
        "pages": pages, "errors": errors,
    }
    (output_dir / "crawl-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    with (output_dir / "page-inventory.csv").open("w", newline="", encoding="utf-8-sig") as stream:
        fields = ["url", "status", "http_status", "page_type", "title", "filename", "sha256", "source_id",
                  "segment_count", "candidates", "missing_fields", "outgoing_same_shop_links", "note"]
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for page in pages:
            writer.writerow({**page, "candidates": json.dumps(page["candidates"], ensure_ascii=False),
                             "missing_fields": "|".join(page["missing_fields"])})
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="遍历 Alibaba 店铺分类/商品页，并把原始 HTML 导入 V13")
    parser.add_argument("--start-url", default=DEFAULT_START)
    parser.add_argument("--seed-url", action="append", default=[], help="额外店铺分类/商品列表入口，可重复指定")
    parser.add_argument("--database", type=Path, default=DEFAULT_DB)
    parser.add_argument("--output-dir", type=Path, default=Path("artifacts/alibaba-shop-v13"))
    parser.add_argument("--max-pages", type=int, default=DEFAULT_MAX_PAGES)
    parser.add_argument("--delay", type=float, default=1.0)
    parser.add_argument("--timeout", type=float, default=20.0)
    args = parser.parse_args(argv)
    try:
        report = crawl(args.start_url, seed_urls=args.seed_url, max_pages=args.max_pages, delay=args.delay, timeout=args.timeout,
                       database=args.database, output_dir=args.output_dir)
        print(json.dumps({k: v for k, v in report.items() if k not in {"pages", "errors"}},
                         ensure_ascii=False, indent=2))
        return 2 if report["captcha_blocked"] or report["pages_failed_or_blocked"] else 0
    except (ValueError, RuntimeError, OSError) as exc:
        print(f"店铺遍历失败：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
