"""Read-only DOM extraction JavaScript for supplier storefronts."""
from __future__ import annotations


LISTING_JS = r"""
() => {
  const clean = value => (value || "").replace(/\s+/g, " ").trim();
  const visible = el => {
    const r = el.getBoundingClientRect(), s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && s.visibility !== "hidden" && s.display !== "none";
  };
  return Array.from(document.querySelectorAll('a[href*="/product-detail/"]'))
    .filter(visible).map(a => {
      const title = clean(a.innerText || a.getAttribute("title") || a.getAttribute("aria-label"));
      let node = a, card = null;
      for (let i = 0; i < 9 && node; i++, node = node.parentElement) {
        const text = clean(node.innerText);
        if (text.length >= 20 && text.length <= 1800 &&
            /(?:CN¥|CNY|RMB|¥|US\s*\$|Min\.?\s*order|Min\.?\s*Order)/i.test(text)) {
          card = node; break;
        }
      }
      const image = (card || a).querySelector("img");
      return {title, url:a.href,
        image_url:image ? (image.currentSrc || image.src || image.getAttribute("data-src") || "") : "",
        card_text:clean(card ? card.innerText : a.innerText)};
    }).filter(item => item.url && item.title);
}
"""
META_JS = r"""
() => {
  const clean = value => (value || "").replace(/\s+/g, " ").trim();
  const links = Array.from(document.querySelectorAll("a[href]")).map(a => ({
    label: clean(a.innerText), url: a.href
  })).filter(a => a.label && /productgrouplist|productlist|company_profile|feedback/i.test(a.url));
  return {page_title:document.title, page_url:location.href,
    category_links:links, page_text:document.body ? document.body.innerText : ""};
}
"""
DETAIL_JS = r"""
() => {
  const clean = value => (value || "").replace(/\s+/g, " ").trim();
  const visible = el => {
    const r = el.getBoundingClientRect(), s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && s.visibility !== "hidden" && s.display !== "none";
  };
  const rows = Array.from(document.querySelectorAll("table")).flatMap(table =>
    Array.from(table.querySelectorAll("tr")).map(row =>
      Array.from(row.querySelectorAll("th,td")).map(cell => clean(cell.innerText))
    )
  ).filter(row => row.length && row.some(Boolean));
  const definitions = Array.from(document.querySelectorAll("dt")).map(dt => {
    const dd = dt.nextElementSibling;
    return [clean(dt.innerText), clean(dd && dd.innerText)];
  }).filter(row => row[0] || row[1]);
  const imageDetails = Array.from(document.querySelectorAll("img"))
    .filter(visible).map(img => ({
      url: img.currentSrc || img.src || img.getAttribute("data-src") || "",
      alt: clean(img.getAttribute("alt") || ""),
      title: clean(img.getAttribute("title") || "")
    })).filter(img => /^https?:\/\//i.test(img.url));
  const metaTags = Array.from(document.querySelectorAll("meta[name],meta[property],meta[itemprop]"))
    .map(meta => ({
      key: meta.getAttribute("name") || meta.getAttribute("property") || meta.getAttribute("itemprop") || "",
      value: meta.getAttribute("content") || ""
    })).filter(meta => meta.key && meta.value);
  const jsonLd = [], jsonLdErrors = [];
  Array.from(document.querySelectorAll('script[type="application/ld+json"]')).forEach((script, index) => {
    try { jsonLd.push({script_index:index + 1, data:JSON.parse(script.textContent || "null")}); }
    catch (error) { jsonLdErrors.push({script_index:index + 1, error:String(error)}); }
  });
  const labelFor = el => {
    if (el.id) {
      const label = document.querySelector('label[for="' + CSS.escape(el.id) + '"]');
      if (label) return clean(label.innerText);
    }
    const parent = el.closest("label");
    if (parent) return clean(parent.innerText);
    return clean(el.getAttribute("aria-label") || el.getAttribute("title") || "");
  };
  const optionGroups = Array.from(document.querySelectorAll("select")).filter(visible).map((el, index) => ({
    kind:"select",
    group:labelFor(el) || clean(el.name || el.getAttribute("aria-label") || ("select_" + (index + 1))),
    options:Array.from(el.options).map(option => ({
      label:clean(option.textContent), value:option.value,
      selected:!!option.selected, disabled:!!option.disabled
    })).filter(option => option.label || option.value)
  }));
  const choiceElements = Array.from(document.querySelectorAll(
    'input[type="radio"],[role="radio"],[role="option"],[data-sku-id],[data-sku-value]'
  )).filter(visible);
  const grouped = new Map();
  choiceElements.forEach((el, index) => {
    const group = clean(el.name || el.closest('[role="radiogroup"]')?.getAttribute("aria-label") ||
      el.closest("[data-sku-property]")?.getAttribute("data-sku-property") ||
      el.closest("fieldset")?.querySelector("legend")?.innerText || "product_option");
    if (!grouped.has(group)) grouped.set(group, []);
    grouped.get(group).push({
      label:labelFor(el) || clean(el.getAttribute("data-value") || el.getAttribute("data-sku-value") ||
        el.getAttribute("aria-label") || el.getAttribute("title") || el.value || el.innerText || ("option_" + (index + 1))),
      value:el.getAttribute("data-sku-value") || el.getAttribute("data-value") || el.value || "",
      selected:el.checked === true || el.getAttribute("aria-checked") === "true" ||
        /\b(selected|active|checked)\b/i.test(String(el.className || "")),
      disabled:el.disabled === true || el.getAttribute("aria-disabled") === "true"
    });
  });
  for (const [group, options] of grouped.entries()) {
    optionGroups.push({kind:"choice", group, options});
  }
  const canonical = document.querySelector('link[rel="canonical"]');
  const ogImage = document.querySelector('meta[property="og:image"]');
  const links = Array.from(document.querySelectorAll("a[href]")).filter(visible).map(a => ({
    label:clean(a.innerText || a.getAttribute("aria-label") || ""),
    url:a.href
  })).filter(link => link.label && /^https?:\/\//i.test(link.url)).slice(0, 300);
  return {
    title:document.title || "",
    canonical_url:canonical ? canonical.href : location.href,
    og_image:ogImage ? ogImage.content : "",
    image_urls:Array.from(new Set(imageDetails.map(img => img.url))),
    image_details:imageDetails,
    table_rows:rows,
    definition_rows:definitions,
    meta_tags:metaTags,
    json_ld:jsonLd,
    json_ld_errors:jsonLdErrors,
    option_groups:optionGroups,
    links:links,
    body_text:document.body ? document.body.innerText : ""
  };
}
"""
