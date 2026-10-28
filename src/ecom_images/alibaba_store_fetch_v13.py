"""Bounded public-page fetching for the Dele Alibaba storefront; no challenge bypass."""
from __future__ import annotations
import hashlib
import re
import urllib.error
import urllib.request
from urllib.parse import parse_qsl,urlencode,urljoin,urlsplit,urlunsplit

STORE_URL="https://dgdeler.en.alibaba.com/"
STORE_HOST="dgdeler.en.alibaba.com"
CRAWLER_VERSION="1.0"
MAX_PAGE_BYTES=8*1024*1024
DEFAULT_MAX_PAGES=250
DEFAULT_DELAY_SECONDS=1.5
KNOWN_STORE_PATHS=(
"/productlist.html",
"/productgrouplist-969259699/Hot_sale_products.html",
"/productgrouplist-915807484/Accessories.html",
"/productgrouplist-965193907/Hinge.html",
"/productgrouplist-911685802/Damping_Hinge.html",
"/productgrouplist-911681003/Torque_Hinge.html",
"/productgrouplist-911700201/Hasp.html",
"/productgrouplist-964646407/Lock.html",
"/productgrouplist-911340706/Lock_cylinder.html",
"/productgrouplist-963643922/Plane_lock.html",
"/productgrouplist-963528746/Handle.html",
"/productgrouplist-0/Ungrouped.html",
"/company_profile.html",
"/company_profile/feedback.html",
)


def is_product_url(url:str)->bool:
    """Recognize common product-detail URL paths without guessing product IDs."""
    path=urlsplit(url).path.casefold()
    return "product-detail" in path or "/productdetail/" in path


def canonicalize_store_url(url:str,base_url:str=STORE_URL)->str|None:
    """Resolve links and restrict crawling to this store or linked Alibaba product details."""
    absolute=urljoin(base_url,url.strip()); parsed=urlsplit(absolute)
    if parsed.scheme not in {"http","https"} or not parsed.hostname or parsed.username or parsed.password:
        return None
    if parsed.port not in (None,443,80): return None
    host=parsed.hostname.casefold()
    if host!=STORE_HOST and not (host=="www.alibaba.com" and is_product_url(absolute)): return None
    query=[(k,v) for k,v in parse_qsl(parsed.query,keep_blank_values=True)
           if k.casefold() not in {"spm","tracelog","from","wx_navbar_transparent","prefetchkey"}]
    return urlunsplit(("https",host,parsed.path or "/",urlencode(query,doseq=True), ""))


def page_slug(url:str)->str:
    """Create a deterministic, filesystem-safe page name."""
    path=urlsplit(url).path.rstrip("/").split("/")[-1] or "store-home"
    stem=re.sub(r"[^A-Za-z0-9._-]+","-",path).strip("-._")[:80] or "page"
    return f"{stem}-{hashlib.sha256(url.encode('utf-8')).hexdigest()[:10]}"


def _decode_body(body:bytes,content_type:str)->str:
    """Decode a bounded HTML response using its declared charset, then safe fallbacks."""
    match=re.search(r"charset\s*=\s*[\"']?([^;\"'\s]+)",content_type,re.I)
    for encoding in ([match.group(1)] if match else [])+["utf-8","gb18030"]:
        try: return body.decode(encoding)
        except (LookupError,UnicodeDecodeError): pass
    return body.decode("utf-8",errors="replace")


def detect_access_block(status:int,html:str)->str:
    """Detect access challenges and report them without attempting to bypass them."""
    lowered=html[:500_000].casefold()
    if status in {401,403,429,503}: return f"HTTP {status}"
    for marker in ("sorry, we have detected unusual traffic","slide to verify","captcha interception",
                   "please slide to verify","security verification","verify you are human"):
        if marker in lowered: return "平台验证码/反自动化拦截"
    if not html.strip(): return "页面响应为空"
    return ""


class _SameStoreRedirects(urllib.request.HTTPRedirectHandler):
    """Do not follow redirects to unrelated hosts or login pages."""
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        target=canonicalize_store_url(newurl,req.full_url)
        if target is None: raise urllib.error.HTTPError(newurl,code,"拒绝跨域跳转",headers,fp)
        return super().redirect_request(req,fp,code,msg,headers,target)


def fetch_store_page(url:str,*,timeout:float=20.0,max_bytes:int=MAX_PAGE_BYTES,
                     user_agent:str="huangren-v13-public-catalog-crawler/1.0")->dict[str,object]:
    """Fetch one public page with size limits; never solve or evade platform challenges."""
    canonical=canonicalize_store_url(url)
    if canonical is None: return {"status":"rejected","url":url,"reason":"URL 不属于允许的店铺/商品页面范围"}
    request=urllib.request.Request(canonical,headers={
        "User-Agent":user_agent,"Accept":"text/html,application/xhtml+xml;q=0.9,*/*;q=0.1",
        "Accept-Language":"en-US,en;q=0.8,zh-CN;q=0.6"})
    opener=urllib.request.build_opener(_SameStoreRedirects())
    try:
        with opener.open(request,timeout=timeout) as response:
            status=int(response.status); final_url=response.geturl()
            content_type=response.headers.get("Content-Type",""); body=response.read(max_bytes+1)
    except urllib.error.HTTPError as exc:
        body=exc.read(max_bytes+1) if exc.fp else b""
        html=_decode_body(body[:max_bytes],exc.headers.get("Content-Type","") if exc.headers else "")
        blocked=detect_access_block(exc.code,html)
        return {"status":"blocked" if blocked else "http_error","url":canonical,
                "http_status":exc.code,"reason":blocked or str(exc.reason)}
    except (urllib.error.URLError,TimeoutError,OSError,ValueError) as exc:
        return {"status":"error","url":canonical,"reason":f"{type(exc).__name__}: {exc}"}
    if len(body)>max_bytes: return {"status":"rejected","url":final_url,"reason":f"页面超过 {max_bytes} 字节限制"}
    if canonicalize_store_url(final_url) is None:
        return {"status":"rejected","url":canonical,"reason":"最终跳转地址超出允许域名范围"}
    html=_decode_body(body,content_type); blocked=detect_access_block(status,html)
    if blocked: return {"status":"blocked","url":final_url,"http_status":status,"reason":blocked}
    return {"status":"ok","url":final_url,"http_status":status,"html":html,"body_bytes":body,
            "content_type":content_type,"size_bytes":len(body),"sha256":hashlib.sha256(body).hexdigest()}


def classify_store_page(url:str)->str:
    """Classify a page using URL structure only, not assumed product data."""
    path=urlsplit(url).path.casefold()
    if is_product_url(url): return "product_detail"
    if "productlist" in path or "productgrouplist" in path: return "category"
    if "company_profile" in path: return "company_profile"
    if path in {"","/","/index.html"}: return "store_home"
    return "other"
