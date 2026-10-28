# Alibaba 店铺商品资料采集（V13）

目标店铺：https://dgdeler.en.alibaba.com/

## 当前访问检查

2026-10-28 检查时，连接浏览器的店铺概览页可读出以下分类入口：
- https://dgdeler.en.alibaba.com/productlist.html — Products / See all categories
- https://dgdeler.en.alibaba.com/productgrouplist-969259699/Hot_sale_products.html — Hot sale products
- https://dgdeler.en.alibaba.com/productgrouplist-915807484/Accessories.html — Accessories
- https://dgdeler.en.alibaba.com/productgrouplist-965193907/Hinge.html — Hinge
- https://dgdeler.en.alibaba.com/productgrouplist-911685802/Damping_Hinge.html — Damping Hinge
- https://dgdeler.en.alibaba.com/productgrouplist-911681003/Torque_Hinge.html — Torque Hinge
- https://dgdeler.en.alibaba.com/productgrouplist-911700201/Hasp.html — Hasp
- https://dgdeler.en.alibaba.com/productgrouplist-964646407/Lock.html — Lock
- https://dgdeler.en.alibaba.com/productgrouplist-911340706/Lock_cylinder.html — Lock cylinder
- https://dgdeler.en.alibaba.com/productgrouplist-963643922/Plane_lock.html — Plane lock
- https://dgdeler.en.alibaba.com/productgrouplist-963528746/Handle.html — Handle
- https://dgdeler.en.alibaba.com/productgrouplist-0/Ungrouped.html — Ungrouped

The public web fetch was blocked by Alibaba's anti-bot challenge (page content includes “unusual traffic” / “slide to verify”). Those blocked pages are not treated as product evidence. The categories above are observed navigation links, not proof that every category or SKU has been crawled.

## Run the crawler

Run from the repository root on a machine with a local V13 database already initialized and network access to Alibaba:

~~~bash
python scripts/knowledge_ingest_v13.py init
python scripts/crawl_alibaba_shop_v13.py \
  --start-url "https://dgdeler.en.alibaba.com/" \
  --seed-url "https://dgdeler.en.alibaba.com/productlist.html" \
  --seed-url "https://dgdeler.en.alibaba.com/productgrouplist-969259699/Hot_sale_products.html" \
  --seed-url "https://dgdeler.en.alibaba.com/productgrouplist-915807484/Accessories.html" \
  --seed-url "https://dgdeler.en.alibaba.com/productgrouplist-965193907/Hinge.html" \
  --seed-url "https://dgdeler.en.alibaba.com/productgrouplist-911685802/Damping_Hinge.html" \
  --seed-url "https://dgdeler.en.alibaba.com/productgrouplist-911681003/Torque_Hinge.html" \
  --seed-url "https://dgdeler.en.alibaba.com/productgrouplist-911700201/Hasp.html" \
  --seed-url "https://dgdeler.en.alibaba.com/productgrouplist-964646407/Lock.html" \
  --seed-url "https://dgdeler.en.alibaba.com/productgrouplist-911340706/Lock_cylinder.html" \
  --seed-url "https://dgdeler.en.alibaba.com/productgrouplist-963643922/Plane_lock.html" \
  --seed-url "https://dgdeler.en.alibaba.com/productgrouplist-963528746/Handle.html" \
  --seed-url "https://dgdeler.en.alibaba.com/productgrouplist-0/Ungrouped.html" \
  --max-pages 500 --delay 1
~~~

The crawler follows same-host category, listing, pagination and product-looking links that are present in the HTML returned to it. It cannot bypass login, CAPTCHA, anti-bot gates or content rendered only inside a browser session. It continues to other seed pages after one page is blocked, recording the blocked URL separately.

## Outputs and V13 integration

Output folder defaults to artifacts/alibaba-shop-v13/:
- crawl-report.json: crawl summary, URL-by-URL status, literal candidate values and missing fields.
- page-inventory.csv: reviewable spreadsheet inventory.
- html/: exact downloaded HTML snapshots for each imported page.

Every accessible page snapshot is passed to the existing import_document() path as a V13 source, with its source URL, retrieval timestamp, page type and visible-text digest in source metadata. The original HTML is retained under the existing local knowledge_sources/ store with SHA-256 integrity. No accepted claim or SKU-model mapping is created automatically.

The report extracts literal candidates for model/SKU, material, dimensions, MOQ, price and specifications. This is deliberately conservative: SKU variants, finish options, quantity tiers and table associations must be checked against the original page before becoming parameter claims. Fields absent from visible text remain missing; they are not filled from other products or guessed from model numbers.

## Accessing pages blocked by CAPTCHA

If the crawler records a CAPTCHA, open the affected page manually in a browser where you are authorized. Save/export the actual page HTML locally (including pagination pages and each product detail page), then import each snapshot into V13:

~~~bash
python scripts/knowledge_ingest_v13.py import-file \
  --file "artifacts/alibaba-shop-v13/manual/product-page.html" \
  --kind supplier_document --authority user_supplied \
  --document-family "Alibaba supplier storefront" \
  --document-number "https://dgdeler.en.alibaba.com/actual-page-url"
~~~

Do not label browser-visible text transcriptions as original HTML. If only a screenshot or copied visible text is available, preserve it as a separate capture and mark the capture method accurately. Review all failed and blocked rows before describing the crawl as complete.

## Test

~~~bash
python -m unittest discover -s tests -p "test_alibaba_shop_crawl_v13.py" -v
~~~
