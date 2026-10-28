"""Evidence-preserving field extraction and report rendering for supplier product pages."""
from __future__ import annotations
import csv
import json
import re
from pathlib import Path
from typing import Any

_REQUIRED_PRODUCT_FIELDS=("product_name","model","sku_specs","material","dimensions","moq")
_FIELD_LABELS={
"model":("model","model no","model no.","model number","item no","item no.","item number","product code","part no","part number","型号","型号编码","货号"),
"sku_specs":("sku","sku no","sku number","variant","variants","specification","specifications","规格","sku规格","产品规格","型号规格"),
"material":("material","materials","body material","main material","材质","材料"),
"dimensions":("size","sizes","dimension","dimensions","product size","overall size","length","width","height","hole distance","mounting hole","尺寸","外形尺寸","长度","宽度","高度","孔距","开孔尺寸"),
"moq":("moq","minimum order quantity","min order quantity","minimum order","min. order","minimum quantity","起订量","最小起订量","最低订购量"),
"price":("price","unit price","price range","price (usd)","价格","单价"),
"finish":("finish","surface finish","surface treatment","颜色","表面处理","表面工艺"),
}


def _field_for_label(label:str)->str|None:
    """Map only explicit table labels to known product fields."""
    normalized=re.sub(r"[\s:：()._-]+"," ",label).strip().casefold()
    for field,aliases in _FIELD_LABELS.items():
        for alias in aliases:
            candidate=re.sub(r"[\s:：()._-]+"," ",alias).strip().casefold()
            if normalized==candidate or normalized.startswith(candidate+" "): return field
    return None


def extract_product_facts(page:dict[str,Any],source_url:str)->dict[str,Any]:
    """Extract explicit label/value pairs while retaining raw excerpts and missing fields."""
    lines=page.get("lines",[])
    if not isinstance(lines,list): lines=[]
    facts={key:[] for key in _FIELD_LABELS}; sku_specs=[]
    for raw in lines:
        line=str(raw).strip()
        if not line: continue
        cells=[part.strip() for part in line.split("|")]
        for index,cell in enumerate(cells):
            field=_field_for_label(cell)
            value=cells[index+1].strip() if field and index+1<len(cells) else ""
            if field and value and value.casefold() not in {"n/a","na","not available","-"}:
                facts[field].append({"value":value,"raw_excerpt":line,"source_url":source_url})
            elif field and (":" in cell or "：" in cell):
                split=re.split(r"[:：]",cell,maxsplit=1)
                if len(split)==2 and split[1].strip():
                    facts[field].append({"value":split[1].strip(),"raw_excerpt":line,"source_url":source_url})
        if re.search(r"\bsku\b|\bvariant\b|规格|孔距|dimensions?|material|minimum order|(?:^|\s)moq(?:\s|$)",line,re.I):
            sku_specs.append({"value":line,"raw_excerpt":line,"source_url":source_url})
        if len(sku_specs)>=100: break
    title=str(page.get("title") or "").strip()
    product_name=[{"value":title,"raw_excerpt":f"HTML title: {title}","source_url":source_url}] if title else []
    if not facts["sku_specs"]: facts["sku_specs"]=sku_specs
    result={"source_url":source_url,"product_name":product_name,"model":facts["model"],
            "sku_specs":facts["sku_specs"] or sku_specs,"material":facts["material"],
            "dimensions":facts["dimensions"],"moq":facts["moq"],"price":facts["price"],"finish":facts["finish"]}
    result["missing_fields"]=[field for field in _REQUIRED_PRODUCT_FIELDS if not result.get(field)]
    result["extraction_note"]=("仅提取页面中可见的明确标签和值；每个值均保留原文摘录。空字段表示页面中未找到可确认信息，"
        "不是推断值，也不代表供应商一定未提供该信息。")
    return result


def render_product_markdown(product:dict[str,Any],source_sha256:str)->str:
    """Render a searchable Markdown evidence report; missing values remain explicitly empty."""
    lines=["# 阿里国际站商品页面提取记录","",f"- 来源链接：{product['source_url']}",
           f"- 原始页面 SHA-256：{source_sha256}","- 记录状态：网页文本候选，未经过人工参数复核",""]
    labels={"product_name":"商品名称","model":"型号","sku_specs":"SKU/规格","material":"材质",
            "dimensions":"尺寸","moq":"MOQ/起订量","price":"价格","finish":"表面处理"}
    for field,label in labels.items():
        lines.extend([f"## {label}",""]); values=product.get(field,[])
        if not values: lines.extend(["- 页面未找到可确认值（待人工核对）",""]); continue
        for item in values:
            lines.extend([f"- 原文值：{item['value']}",f"  - 原文证据：{item['raw_excerpt']}",
                          f"  - 来源：{item['source_url']}"])
        lines.append("")
    lines.extend(["## 缺失项",""])
    lines.extend([f"- {labels.get(field,field)}" for field in product["missing_fields"]] or ["- 无"])
    lines.extend(["",f"> {product['extraction_note']}",""])
    return "\n".join(lines)


def write_products_csv(path:Path,products:list[dict[str,Any]])->None:
    """Write one product per row, retaining evidence objects as JSON cells."""
    fields=["source_url","source_sha256","source_id","product_name","model","sku_specs","material",
            "dimensions","moq","price","finish","missing_fields"]
    with path.open("w",encoding="utf-8-sig",newline="") as stream:
        writer=csv.DictWriter(stream,fieldnames=fields); writer.writeheader()
        for item in products:
            row={key:item.get(key,[]) for key in fields}
            for key in fields:
                if isinstance(row[key],(list,dict)): row[key]=json.dumps(row[key],ensure_ascii=False)
            writer.writerow(row)


def write_summary_markdown(path:Path,report:dict[str,Any])->None:
    """Write an operator-readable coverage and blocked-page report."""
    lines=["# 阿里国际站店铺采集报告","",f"- 店铺：{report['store_url']}",
        f"- 尝试页面：{report['attempted_pages']}",f"- 成功访问：{report['successful_pages']}",
        f"- 商品详情页：{report['product_pages']}",f"- V13 原始页面来源导入：{report['v13_imported_sources']}",
        f"- V13 商品字段报告导入：{report['v13_imported_product_reports']}","","## 验证码/访问拦截页面",""]
    blocked=report["blocked_pages"]
    lines.extend([f"- [{item['status']}] {item['url']} — {item.get('reason','')}" for item in blocked]
                 if blocked else ["- 本次没有检测到明确的验证码拦截。"])
    lines.extend(["","## 未访问或失败页面",""])
    failed=report["failed_pages"]
    lines.extend([f"- [{item['status']}] {item['url']} — {item.get('reason','')}" for item in failed]
                 if failed else ["- 无"])
    lines.extend(["","## 商品字段缺失概况",""])
    if report["products"]:
        lines.extend([f"- {p['source_url']}：缺失项 {'、'.join(p['missing_fields']) or '无'}"
                      for p in report["products"]])
    else: lines.append("- 本次未能成功读取商品详情页，因此没有可确认的商品字段记录。")
    lines.extend(["","## 限制","",*[f"- {item}" for item in report["limits"]]])
    path.write_text("\n".join(lines)+"\n",encoding="utf-8")
