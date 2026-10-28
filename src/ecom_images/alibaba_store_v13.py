"""Bounded crawler orchestration that imports public storefront evidence into V13."""
from __future__ import annotations
import hashlib
import json
import sqlite3
import time
from datetime import datetime,timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from .alibaba_product_extract_v13 import extract_product_facts,render_product_markdown,write_products_csv,write_summary_markdown
from .alibaba_store_fetch_v13 import (
 CRAWLER_VERSION,DEFAULT_DELAY_SECONDS,DEFAULT_MAX_PAGES,KNOWN_STORE_PATHS,MAX_PAGE_BYTES,
 STORE_URL,canonicalize_store_url,classify_store_page,fetch_store_page,page_slug,
)
from .database_v9 import DEFAULT_DB
from .html_capture_v13 import parse_html_document
from .knowledge_ingest_v13 import MAX_SOURCE_BYTES,import_document


def crawl_store(*,database:str|Path=DEFAULT_DB,output_dir:str|Path,start_url:str=STORE_URL,
                max_pages:int=DEFAULT_MAX_PAGES,delay_seconds:float=DEFAULT_DELAY_SECONDS,
                timeout:float=20.0,max_page_bytes:int=MAX_PAGE_BYTES,
                seed_known_categories:bool=True,import_to_v13:bool=True)->dict[str,Any]:
    """Crawl linked storefront/category/product pages, save evidence, and optionally import into V13."""
    if type(max_pages) is not int or not 1<=max_pages<=5000: raise ValueError("max_pages 必须在 1 到 5000 之间")
    if not isinstance(delay_seconds,(int,float)) or delay_seconds<0.5 or delay_seconds>60:
        raise ValueError("delay_seconds 必须在 0.5 到 60 秒之间，避免高频请求")
    if not 1<=max_page_bytes<=MAX_SOURCE_BYTES:
        raise ValueError(f"max_page_bytes 必须在 1 到 {MAX_SOURCE_BYTES} 之间")
    start=canonicalize_store_url(start_url)
    if start is None: raise ValueError("起始链接必须是 dgdeler.en.alibaba.com 店铺页面")
    root=Path(output_dir).expanduser().absolute(); raw_dir=root/"raw"; derived_dir=root/"derived"
    raw_dir.mkdir(parents=True,exist_ok=True); derived_dir.mkdir(parents=True,exist_ok=True)
    queue=[(start,"用户指定店铺链接")]
    if seed_known_categories:
        queue.extend((canonicalize_store_url(path,STORE_URL),"店铺首页可见导航链接") for path in KNOWN_STORE_PATHS)
    seen:set[str]=set(); content_hashes:dict[str,str]={}; pages:list[dict[str,Any]]=[]; products:list[dict[str,Any]]=[]
    imported_count=0; imported_report_count=0; page_index=0
    while queue and len(seen)<max_pages:
        url,discovered_from=queue.pop(0); canonical=canonicalize_store_url(url or "")
        if not canonical or canonical in seen: continue
        seen.add(canonical)
        if page_index: time.sleep(delay_seconds)
        fetched=fetch_store_page(canonical,timeout=timeout,max_bytes=max_page_bytes); page_index+=1
        entry:dict[str,Any]={"url":canonical,"discovered_from":discovered_from,
            "status":fetched["status"],"reason":fetched.get("reason",""),"http_status":fetched.get("http_status")}
        if fetched["status"]!="ok":
            pages.append(entry); continue
        final_url=str(fetched["url"]); html=str(fetched["html"]); raw_bytes=fetched["body_bytes"]
        parsed=parse_html_document(html,final_url); kind=classify_store_page(final_url); page_sha=str(fetched["sha256"])
        entry.update({"url":final_url,"page_kind":kind,"title":parsed["title"],"sha256":page_sha,
                      "size_bytes":fetched["size_bytes"],"visible_line_count":len(parsed["lines"])})
        raw_path=raw_dir/f"{page_slug(final_url)}-{page_sha[:10]}.html"
        raw_path.write_bytes(raw_bytes); entry["capture_file"]=str(raw_path)
        if page_sha in content_hashes:
            entry["duplicate_content_of"]=content_hashes[page_sha]
        else:
            content_hashes[page_sha]=final_url
            if import_to_v13:
                source_kind="supplier_document" if kind=="product_detail" else "platform_export"
                try:
                    imported=import_document(database,file_path=raw_path,source_kind=source_kind,authority_level="unverified",
                        document_family="Alibaba storefront: Dongguan Dele Hardware Technology Co., Ltd.",
                        source_metadata={"source_url":final_url,"canonical_url":canonical,"page_kind":kind,
                                         "capture_method":"public_http","crawler_version":CRAWLER_VERSION})
                    entry["source_id"]=imported["source_id"]; entry["v13_imported"]=True
                    entry["segment_count"]=imported["segment_count"]; imported_count+=1
                except (ValueError,RuntimeError,OSError,sqlite3.Error) as exc:
                    entry["v13_imported"]=False; entry["import_error"]=f"{type(exc).__name__}: {exc}"
            else: entry["v13_imported"]=False
        if kind=="product_detail":
            product=extract_product_facts(parsed,final_url)
            product["source_sha256"]=page_sha; product["source_id"]=entry.get("source_id","")
            product["capture_file"]=str(raw_path); products.append(product)
            report_file=derived_dir/f"product-{hashlib.sha256(final_url.encode('utf-8')).hexdigest()[:16]}.md"
            report_file.write_text(render_product_markdown(product,page_sha),encoding="utf-8")
            if import_to_v13 and entry.get("source_id"):
                try:
                    derived=import_document(database,file_path=report_file,source_kind="platform_export",
                        authority_level="system_export",document_family="Alibaba storefront extracted field report",
                        source_metadata={"source_url":final_url,"source_page_sha256":page_sha,
                                         "page_kind":"derived_product_field_report","crawler_version":CRAWLER_VERSION})
                    product["derived_report_source_id"]=derived["source_id"]; imported_report_count+=1
                except (ValueError,RuntimeError,OSError,sqlite3.Error) as exc:
                    product["derived_report_import_error"]=f"{type(exc).__name__}: {exc}"
        pages.append(entry)
        for link in parsed["links"]:
            target=canonicalize_store_url(link["url"],final_url)
            if target and target not in seen and len(queue)+len(seen)<max_pages*5:
                path=urlsplit(target).path.casefold()
                if ("/product-detail" in path or "productdetail" in path or "productlist" in path
                    or "productgrouplist" in path or "company_profile" in path or path in {"","/","/index.html"}):
                    queue.append((target,f"页面链接：{final_url}"))
    for url,source in queue:
        canonical=canonicalize_store_url(url or "")
        if canonical and canonical not in seen:
            pages.append({"url":canonical,"status":"not_visited_page_limit",
                          "reason":f"达到 max_pages={max_pages}","discovered_from":source})
    (root/"products.json").write_text(json.dumps(products,ensure_ascii=False,indent=2),encoding="utf-8")
    report={
        "store_url":start,"crawler_version":CRAWLER_VERSION,
        "generated_at":datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "max_pages":max_pages,"delay_seconds":delay_seconds,"attempted_pages":page_index,"visited_urls":len(seen),
        "successful_pages":sum(1 for item in pages if item["status"]=="ok"),
        "blocked_pages":[item for item in pages if item["status"]=="blocked"],
        "failed_pages":[item for item in pages if item["status"] not in {"ok","blocked"}],
        "queued_not_visited":sum(1 for item in pages if item["status"]=="not_visited_page_limit"),
        "product_pages":len(products),"v13_imported_sources":imported_count,
        "v13_imported_product_reports":imported_report_count,"pages":pages,"products":products,
        "limits":[
            "仅抓取公开页面，不使用登录 Cookie、不绕过验证码或反自动化措施。",
            "未出现在可访问 HTML 中的动态 SKU 变体、图片文字和隐藏字段不会被猜测。",
            "字段缺失表示本次页面文本未找到明确标签和值，不等于供应商没有提供。",
            "产品页面值是供应商网页声明，尚未经过人工复核或独立认证。",
        ],
    }
    (root/"crawl_report.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    write_products_csv(root/"products.csv",products); write_summary_markdown(root/"crawl_report.md",report)
    return report
