from __future__ import annotations
import csv,hashlib,io,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT/"src"))
from ecom_images.alibaba_product_extract_v13 import extract_product_facts,render_product_markdown
from ecom_images.alibaba_store_fetch_v13 import STORE_URL,canonicalize_store_url,detect_access_block
from ecom_images.alibaba_store_v13 import crawl_store
from ecom_images.catalog_v12 import COLUMNS,import_catalog_csv
from ecom_images.database_v9 import open_database,save_job
from ecom_images.html_capture_v13 import parse_html_document
from ecom_images.knowledge_ingest_v13 import import_document,search_knowledge
from ecom_images.knowledge_schema_v13 import initialize_knowledge
from ecom_images.production_ledger_v6 import new_record


def _catalog_csv()->bytes:
    """Build a tiny synthetic catalog for isolated V13 tests."""
    row={"店铺编码":"SHOP-1","店铺名称":"测试店铺","平台":"阿里国际站","商品编码":"P-1",
         "商品名称":"测试锁具","商品类别":"工业锁具","SKU编码":"SKU-1","产品型号":"TEST-1",
         "材质":"","表面处理":"","孔距(mm)":"","总长(mm)":"","备注":""}
    stream=io.StringIO(newline=""); writer=csv.DictWriter(stream,fieldnames=COLUMNS)
    writer.writeheader(); writer.writerow(row)
    return ("\ufeff"+stream.getvalue()).encode("utf-8")


class AlibabaStoreV13Tests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name); self.db=self.root/"knowledge.sqlite3"
        save_job(self.db,new_record([("test.jpg",b"synthetic",{})],fingerprint="b"*64,platform="阿里国际站",template="测试"))
        import_catalog_csv(self.db,_catalog_csv(),dry_run=False); initialize_knowledge(self.db)

    def test_html_parser_keeps_title_table_rows_links_and_skips_scripts(self):
        html="""<!doctype html><html><head><title>Lock Product</title>
        <meta name="description" content="Industrial cabinet lock"></head><body><h1>MS705 Lock</h1>
        <script>FAKE_MODEL = 'NO-123';</script><table><tr><th>Material</th><th>Stainless Steel</th></tr>
        <tr><td>MOQ</td><td>50 pcs</td></tr></table>
        <a href="/productlist.html?pageNum=2">Next</a></body></html>"""
        parsed=parse_html_document(html,STORE_URL)
        self.assertEqual(parsed["title"],"Lock Product")
        self.assertTrue(any("Material | Stainless Steel" in line for line in parsed["lines"]))
        self.assertTrue(any("MOQ | 50 pcs" in line for line in parsed["lines"]))
        self.assertFalse(any("FAKE_MODEL" in line for line in parsed["lines"]))
        self.assertTrue(any(link["url"].endswith("/productlist.html?pageNum=2") for link in parsed["links"]))

    def test_url_scope_keeps_pagination_but_removes_tracking(self):
        url=canonicalize_store_url("https://dgdeler.en.alibaba.com/productlist.html?spm=abc&pageNum=2#products")
        self.assertEqual(url,"https://dgdeler.en.alibaba.com/productlist.html?pageNum=2")
        self.assertIsNone(canonicalize_store_url("https://example.com/steal"))
        self.assertIsNone(canonicalize_store_url("https://www.alibaba.com/login.htm"))

    def test_access_challenge_is_reported_not_bypassed(self):
        self.assertIn("验证码",detect_access_block(200,"Sorry, we have detected unusual traffic"))
        self.assertEqual(detect_access_block(429,"slow down"),"HTTP 429")
        self.assertEqual(detect_access_block(200,"<html><body>public product</body></html>"),"")

    def test_product_facts_keep_raw_evidence_and_explicit_missing_fields(self):
        parsed=parse_html_document("""<html><head><title>MS705 Cabinet Lock</title></head><body><table>
        <tr><td>Model No.</td><td>MS705</td></tr><tr><td>Material</td><td>Zinc Alloy</td></tr>
        <tr><td>Dimensions</td><td>20 x 22.5 mm opening</td></tr>
        <tr><td>Minimum Order Quantity</td><td>10 pieces</td></tr>
        <tr><td>SKU</td><td>MS705-3 triangle key</td></tr></table></body></html>""",
        "https://dgdeler.en.alibaba.com/product-detail/ms705.html")
        facts=extract_product_facts(parsed,"https://dgdeler.en.alibaba.com/product-detail/ms705.html")
        self.assertEqual(facts["product_name"][0]["value"],"MS705 Cabinet Lock")
        self.assertEqual(facts["model"][0]["value"],"MS705")
        self.assertEqual(facts["material"][0]["value"],"Zinc Alloy")
        self.assertEqual(facts["dimensions"][0]["value"],"20 x 22.5 mm opening")
        self.assertEqual(facts["moq"][0]["value"],"10 pieces")
        self.assertTrue(any("SKU" in row["raw_excerpt"] for row in facts["sku_specs"]))
        self.assertIn("price",facts["missing_fields"]); self.assertIn("source_url",facts["material"][0])
        report=render_product_markdown(facts,"a"*64)
        self.assertIn("来源链接：https://dgdeler.en.alibaba.com/product-detail/ms705.html",report)
        self.assertIn("页面未找到可确认值",report)

    def test_html_import_preserves_source_url_and_searchable_evidence(self):
        path=self.root/"captured.html"
        path.write_text("""<html><head><title>MS705 Lock</title></head><body><table>
        <tr><td>Model</td><td>MS705</td></tr><tr><td>Material</td><td>Zinc Alloy</td></tr>
        <tr><td>MOQ</td><td>10 pcs</td></tr></table></body></html>""",encoding="utf-8")
        source_url="https://dgdeler.en.alibaba.com/product-detail/ms705.html"
        result=import_document(self.db,file_path=path,source_kind="supplier_document",authority_level="unverified",
            source_metadata={"source_url":source_url,"page_kind":"product_detail"})
        found=search_knowledge(self.db,query="MS705")
        item=next(row for row in found["results"] if row["type"]=="document")
        self.assertEqual(item["source_metadata"]["source_url"],source_url)
        self.assertEqual(item["source_id"],result["source_id"])
        with open_database(self.db) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM knowledge_claims").fetchone()[0],0)

    def test_same_html_hash_cannot_silently_change_source_url(self):
        path=self.root/"captured.html"; path.write_text("<html><body><h1>Model MS705</h1></body></html>",encoding="utf-8")
        import_document(self.db,file_path=path,source_kind="supplier_document",
            source_metadata={"source_url":"https://dgdeler.en.alibaba.com/a.html"})
        with self.assertRaisesRegex(ValueError,"来源 URL/元数据不一致"):
            import_document(self.db,file_path=path,source_kind="supplier_document",
                source_metadata={"source_url":"https://dgdeler.en.alibaba.com/b.html"})

    def test_crawler_imports_fixture_pages_and_writes_missing_field_report(self):
        pages={
          "https://dgdeler.en.alibaba.com/":"""<html><head><title>Dele</title></head><body><a href="/productlist.html">Products</a></body></html>""",
          "https://dgdeler.en.alibaba.com/productlist.html":"""<html><body><a href="/product-detail/ms705.html">MS705 lock</a></body></html>""",
          "https://dgdeler.en.alibaba.com/product-detail/ms705.html":"""<html><head><title>MS705 Lock</title></head><body><table>
          <tr><td>Model</td><td>MS705</td></tr><tr><td>Material</td><td>Zinc Alloy</td></tr>
          <tr><td>MOQ</td><td>10 pcs</td></tr></table></body></html>""",
        }
        def fake_fetch(url,**kwargs):
            html=pages[url]; raw=html.encode("utf-8")
            return {"status":"ok","url":url,"http_status":200,"html":html,"body_bytes":raw,
                "content_type":"text/html; charset=utf-8","size_bytes":len(raw),"sha256":hashlib.sha256(raw).hexdigest()}
        output=self.root/"captures"
        with patch("ecom_images.alibaba_store_v13.fetch_store_page",side_effect=fake_fetch), \
             patch("ecom_images.alibaba_store_v13.time.sleep"):
            report=crawl_store(database=self.db,output_dir=output,max_pages=3,delay_seconds=0.5,seed_known_categories=False)
        self.assertEqual(report["successful_pages"],3); self.assertEqual(report["product_pages"],1)
        self.assertEqual(report["v13_imported_sources"],3); self.assertEqual(report["v13_imported_product_reports"],1)
        self.assertTrue((output/"crawl_report.json").is_file()); self.assertTrue((output/"products.csv").is_file())
        product=report["products"][0]; self.assertEqual(product["model"][0]["value"],"MS705")
        self.assertIn("dimensions",product["missing_fields"]); self.assertIn("moq",product)
        found=search_knowledge(self.db,query="MS705")
        self.assertTrue(any(row["type"]=="document" for row in found["results"]))


if __name__=="__main__": unittest.main(verbosity=2)
