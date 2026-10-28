"""Human-in-the-loop CLI for capturing public Alibaba supplier catalog pages."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from ecom_images.supplier_catalog_capture import (  # noqa: E402
    DEFAULT_URL, DETAIL_JS, is_challenge, product_fingerprint, save_listing_outputs,
    scrape_listing_page, write_detail_exports,
)

DEFAULT_OUTPUT = ROOT / "data" / "supplier_captures" / "dgdeler"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse listing and detail capture options."""
    parser = argparse.ArgumentParser(
        description="Capture public Alibaba supplier listings and details using a visible browser."
    )
    sub = parser.add_subparsers(dest="command", required=True)
    listing = sub.add_parser("listing", help="Capture all visible pages in a supplier listing.")
    listing.add_argument("--url", default=DEFAULT_URL)
    listing.add_argument("--max-pages", type=int, default=139)
    listing.add_argument("--delay", type=float, default=2.5)
    listing.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    listing.add_argument("--profile-dir", type=Path, default=ROOT / ".local-browser-profile" / "alibaba")
    listing.add_argument("--save-html", action="store_true", help="Save page HTML locally for audit.")
    details = sub.add_parser("details", help="Visit captured product links and save visible detail text.")
    details.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    details.add_argument("--profile-dir", type=Path, default=ROOT / ".local-browser-profile" / "alibaba")
    details.add_argument("--delay", type=float, default=3.0)
    details.add_argument("--limit", type=int, default=0, help="Optional maximum number of products; 0 means all.")
    details.add_argument("--save-html", action="store_true", help="Save detail page HTML locally for audit.")
    audit = sub.add_parser("audit", help="Rebuild exports and report missing listing pages/details.")
    audit.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args(argv)


def launch_browser(profile_dir: Path):
    """Launch a visible persistent Chromium profile for manual login and verification."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError(
            "缺少 Playwright。执行 python -m pip install -r requirements-supplier-capture.txt，"
            "再执行 python -m playwright install chromium。"
        ) from exc
    playwright = sync_playwright().start()
    profile_dir.mkdir(parents=True, exist_ok=True)
    context = playwright.chromium.launch_persistent_context(
        user_data_dir=str(profile_dir), headless=False,
        viewport={"width": 1440, "height": 1000}, locale="en-US",
    )
    page = context.pages[0] if context.pages else context.new_page()
    return playwright, context, page


def wait_for_manual_check(page, label: str) -> None:
    """Pause for a person to complete a site-provided check; never bypass a CAPTCHA."""
    while True:
        body = page.locator("body").inner_text(timeout=10000)
        if not is_challenge(body, page.url):
            return
        print(f"\n检测到可能的登录/验证码页面：{label}")
        print("请在浏览器窗口手动完成验证；程序不会自动绕过验证码。")
        input("完成后回到终端按 Enter 继续；无法通过时按 Ctrl+C 停止：")
        page.wait_for_timeout(1200)


def click_page_number(page, target: int, old_fingerprint: str) -> bool:
    """Click the visible next numeric page button or a clearly labelled next control."""
    clicked = page.evaluate(
        r"""target => {
          const visible = el => {
            const r = el.getBoundingClientRect(), s = getComputedStyle(el);
            return r.width > 0 && r.height > 0 && s.display !== "none" && s.visibility !== "hidden";
          };
          const controls = Array.from(document.querySelectorAll('button,a,[role="button"]')).filter(visible);
          const exact = controls.find(el => (el.innerText || "").trim() === String(target) && !el.disabled);
          if (exact) { exact.click(); return true; }
          const next = controls.find(el => {
            const label = ((el.innerText || "") + " " + (el.getAttribute("aria-label") || "") +
              " " + (el.getAttribute("title") || "") + " " + (el.className || "")).toLowerCase();
            return !el.disabled && (/\bnext\b/.test(label) || /next-page/.test(label) ||
              /pagination-next/.test(label) || (el.innerText || "").trim() === ">");
          });
          if (next) { next.click(); return true; }
          return false;
        }""",
        target,
    )
    if not clicked:
        return False
    try:
        page.wait_for_function(
            "old => Array.from(document.querySelectorAll('a[href*=\"/product-detail/\"]'))"
            ".map(a=>a.href).filter(Boolean).slice(0,30).join('|') !== old",
            arg=old_fingerprint, timeout=20000,
        )
    except Exception:
        page.wait_for_timeout(1800)
    return product_fingerprint(page) != old_fingerprint


def run_listing(args: argparse.Namespace) -> int:
    """Capture listing pages one by one and save a checkpoint after every page."""
    if args.max_pages < 1:
        raise ValueError("--max-pages must be at least 1")
    output = args.output.resolve()
    pages_dir = output / "pages"
    pages_dir.mkdir(parents=True, exist_ok=True)
    playwright, context, page = launch_browser(args.profile_dir.resolve())
    try:
        page.goto(args.url, wait_until="domcontentloaded", timeout=90000)
        page.wait_for_timeout(1800)
        print("浏览器已打开。请在窗口中确认商品列表可见，并手动完成需要的登录/验证。")
        input("准备好后回到终端按 Enter 开始采集：")
        wait_for_manual_check(page, "商品列表")
        for number in range(1, args.max_pages + 1):
            wait_for_manual_check(page, f"商品列表第 {number} 页")
            fingerprint = product_fingerprint(page)
            checkpoint = pages_dir / f"page_{number:03d}.json"
            if checkpoint.exists():
                print(f"[{number}/{args.max_pages}] 已有检查点；仍会翻页以保持进度。")
            else:
                record = scrape_listing_page(page, number, args.url)
                checkpoint.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                if args.save_html:
                    (pages_dir / f"page_{number:03d}.html").write_text(page.content(), encoding="utf-8")
                print(f"[{number}/{args.max_pages}] 保存 {record['visible_item_count']} 条可见商品。")
                print(json.dumps(save_listing_outputs(output), ensure_ascii=False))
            if number >= args.max_pages:
                break
            if not click_page_number(page, number + 1, fingerprint):
                print(f"找不到第 {number + 1} 页的分页按钮。现有检查点已保留，可调整页面后重试。")
                break
            page.wait_for_timeout(max(0.5, args.delay) * 1000)
        print(json.dumps(save_listing_outputs(output), ensure_ascii=False, indent=2))
        return 0
    finally:
        context.close()
        playwright.stop()


def run_details(args: argparse.Namespace) -> int:
    """Capture visible product details at a respectful pace and checkpoint each product."""
    catalog_path = args.output.resolve() / "catalog.json"
    if not catalog_path.exists():
        raise FileNotFoundError(f"未找到目录 {catalog_path}；请先运行 listing 子命令。")
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    items = catalog.get("items", [])
    if args.limit > 0:
        items = items[:args.limit]
    detail_dir = args.output.resolve() / "details"
    detail_dir.mkdir(parents=True, exist_ok=True)
    playwright, context, page = launch_browser(args.profile_dir.resolve())
    try:
        page.goto(DEFAULT_URL, wait_until="domcontentloaded", timeout=90000)
        page.wait_for_timeout(1200)
        print("详情页将按间隔逐个访问；若出现登录/验证码，请手动处理。")
        input("准备好后回到终端按 Enter 开始：")
        for index, item in enumerate(items, start=1):
            item_id = item.get("item_id") or hashlib.sha256(item["product_url"].encode()).hexdigest()[:16]
            path = detail_dir / f"{item_id}.json"
            if path.exists():
                try:
                    prior = json.loads(path.read_text(encoding="utf-8"))
                    prior_text = detail_dir / f"{item_id}.txt"
                    if isinstance(prior, dict) and isinstance(prior.get("detail_page"), dict) and prior_text.exists():
                        print(f"[{index}/{len(items)}] 跳过已保存详情：{item.get('title', item_id)}")
                        continue
                    print(f"[{index}/{len(items)}] 详情记录不完整，将重新采集：{item.get('title', item_id)}")
                except (OSError, json.JSONDecodeError):
                    print(f"[{index}/{len(items)}] 详情 JSON 无法读取，将重新采集：{item.get('title', item_id)}")
            page.goto(item["product_url"], wait_until="domcontentloaded", timeout=90000)
            page.wait_for_timeout(1200)
            wait_for_manual_check(page, f"商品详情 {item.get('title', item_id)}")
            detail = page.evaluate(DETAIL_JS)
            body_text = detail.pop("body_text", "")
            detail["body_text_file"] = f"{item_id}.txt"
            record = {
                "item_id": item_id,
                "listing_title": item.get("title"),
                "listing_url": item.get("product_url"),
                "captured_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "detail_url": page.url,
                "detail_page": detail,
                "verification_status": "visible_detail_page_observation_unverified",
            }
            path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            (detail_dir / f"{item_id}.txt").write_text(body_text, encoding="utf-8")
            if args.save_html:
                (detail_dir / f"{item_id}.html").write_text(page.content(), encoding="utf-8")
            print(f"[{index}/{len(items)}] 已保存详情：{item.get('title', item_id)}")
            page.wait_for_timeout(max(1.0, args.delay) * 1000)
        detail_audit = write_detail_exports(args.output.resolve())
        print(json.dumps(detail_audit, ensure_ascii=False, indent=2))
        print(f"详情采集结束。文件目录：{detail_dir}")
        return 0
    finally:
        context.close()
        playwright.stop()


def main(argv: list[str] | None = None) -> int:
    """Run the requested capture mode and return a process exit code."""
    args = parse_args(argv)
    try:
        if args.command == "listing":
            return run_listing(args)
        if args.command == "details":
            return run_details(args)
        output = args.output.resolve()
        pages_dir = output / "pages"
        if not pages_dir.exists() or not list(pages_dir.glob("page_*.json")):
            raise FileNotFoundError(f"未找到商品分页检查点：{pages_dir}；请先运行 listing 子命令。")
        listing_summary = save_listing_outputs(output)
        detail_summary = write_detail_exports(output)
        print(json.dumps({"listing": listing_summary, "details": detail_summary}, ensure_ascii=False, indent=2))
        return 0 if listing_summary.get("audit_status") == "complete" and detail_summary.get("is_complete") else 2
    except KeyboardInterrupt:
        print("\n已中止；已保存的检查点会保留。", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"采集失败：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
