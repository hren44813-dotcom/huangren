"""Command-line argument parsing and visible-browser helper functions."""
from __future__ import annotations
import argparse
from pathlib import Path
from ..supplier_catalog_capture import DEFAULT_URL, is_challenge, product_fingerprint

ROOT = Path(__file__).resolve().parents[3]
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
    listing.add_argument("--headless", action="store_true", help="Run Chromium without a visible window; no manual CAPTCHA solving is possible.")
    listing.add_argument("--no-prompt", action="store_true", help="Do not wait for terminal input; abort if a human check is required.")
    listing.add_argument("--refresh-existing", action="store_true", help="Recapture existing checkpoints while traversing pages, useful for price-history snapshots.")
    details = sub.add_parser("details", help="Visit captured product links and save visible detail text.")
    details.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    details.add_argument("--profile-dir", type=Path, default=ROOT / ".local-browser-profile" / "alibaba")
    details.add_argument("--delay", type=float, default=3.0)
    details.add_argument("--limit", type=int, default=0, help="Optional maximum number of products; 0 means all.")
    details.add_argument("--save-html", action="store_true", help="Save detail page HTML locally for audit.")
    details.add_argument("--headless", action="store_true", help="Run Chromium without a visible window; no manual CAPTCHA solving is possible.")
    details.add_argument("--no-prompt", action="store_true", help="Do not wait for terminal input; abort if a human check is required.")
    details.add_argument("--retries", type=int, default=2, help="Retries per product after ordinary navigation errors.")
    audit = sub.add_parser("audit", help="Rebuild exports and report missing listing pages/details.")
    audit.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args(argv)


def launch_browser(profile_dir: Path, *, headless: bool = False):
    """Launch a persistent Chromium profile; headless mode cannot complete manual checks."""
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
        user_data_dir=str(profile_dir), headless=headless,
        viewport={"width": 1440, "height": 1000}, locale="en-US",
    )
    page = context.pages[0] if context.pages else context.new_page()
    return playwright, context, page


def wait_for_manual_check(page, label: str, *, interactive: bool = True) -> None:
    """Pause for a person to complete a site-provided check; never bypass a CAPTCHA."""
    while True:
        body = page.locator("body").inner_text(timeout=10000)
        if not is_challenge(body, page.url):
            return
        if not interactive:
            raise RuntimeError(
                f"检测到登录/验证码或访问限制（{label}）。非交互模式已停止；不会尝试绕过验证。"
            )
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
            "old => {const current = Array.from(document.querySelectorAll('a[href*=\\\"/product-detail/\\\"]'))"
            ".map(a=>a.href).filter(Boolean).slice(0,30).join('|'); return !!current && current !== old;}",
            arg=old_fingerprint, timeout=20000,
        )
    except Exception:
        page.wait_for_timeout(1800)
    current = product_fingerprint(page)
    return bool(current and current != old_fingerprint)
