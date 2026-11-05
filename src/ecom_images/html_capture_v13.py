"""Safe, dependency-free visible-text extraction for HTML source snapshots."""
from __future__ import annotations
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

_BLOCK_TAGS={"address","article","aside","blockquote","br","dd","div","dl","dt","fieldset","figcaption","figure","footer","form","h1","h2","h3","h4","h5","h6","header","hr","li","main","nav","ol","p","section","ul"}
_SKIP_TAGS={"script","style","noscript","template","svg","iframe"}
_LINK_SCHEMES={"http","https"}


def _clean(value:str)->str:
    """Collapse display whitespace without changing meaningful punctuation."""
    return " ".join(value.replace("\xa0"," ").split()).strip()


class _VisibleParser(HTMLParser):
    """Extract visible lines, table rows, metadata and links."""
    def __init__(self,base_url:str)->None:
        super().__init__(convert_charrefs=True)
        self.base_url=base_url; self.lines=[]; self.links=[]; self.title_parts=[]
        self.description=""; self.og_title=""; self._line=[]; self._cell=None; self._cells=[]
        self._skip_depth=0; self._skip_stack=[]; self._title_depth=0; self._anchor_stack=[]

    def _flush_line(self)->None:
        value=_clean("".join(self._line))
        if value: self.lines.append(value)
        self._line=[]

    def handle_starttag(self,tag,attrs)->None:
        values={key.lower():(value or "") for key,value in attrs}
        if tag in _SKIP_TAGS:
            self._skip_depth+=1; self._skip_stack.append(tag); return
        if self._skip_depth: return
        if tag=="meta":
            name=values.get("name","").casefold(); prop=values.get("property","").casefold()
            if name=="description" and values.get("content"): self.description=_clean(values["content"])
            if prop=="og:title" and values.get("content"): self.og_title=_clean(values["content"])
        if tag=="title": self._title_depth+=1
        if tag=="tr": self._flush_line(); self._cells=[]; self._cell=None
        elif tag in {"td","th"}: self._cell=[]
        elif tag in _BLOCK_TAGS and self._cell is None: self._flush_line()
        if tag=="img" and values.get("alt"): self._line.append(f" {values['alt']} ")
        if tag=="a": self._anchor_stack.append({"href":values.get("href","").strip(),"text":[]})

    def handle_data(self,data:str)->None:
        if self._skip_depth or not data: return
        if self._title_depth: self.title_parts.append(data)
        if self._cell is not None: self._cell.append(data)
        else: self._line.append(data)
        if self._anchor_stack: self._anchor_stack[-1]["text"].append(data)

    def handle_endtag(self,tag)->None:
        if self._skip_depth:
            if tag==self._skip_stack[-1]: self._skip_stack.pop(); self._skip_depth-=1
            return
        if tag=="title" and self._title_depth: self._title_depth-=1
        if tag in {"td","th"} and self._cell is not None:
            self._cells.append(_clean("".join(self._cell))); self._cell=None
        elif tag=="tr":
            self._flush_line(); cells=[cell for cell in self._cells if cell]
            if cells: self.lines.append(" | ".join(cells))
            self._cells=[]; self._cell=None
        elif tag=="a" and self._anchor_stack:
            anchor=self._anchor_stack.pop(); href=str(anchor["href"])
            parsed=urlsplit(urljoin(self.base_url,href)); label=_clean("".join(anchor["text"]))
            if parsed.scheme in _LINK_SCHEMES and parsed.netloc:
                self.links.append({"text":label,"url":parsed.geturl()})
        elif tag in _BLOCK_TAGS and self._cell is None: self._flush_line()

    def close(self)->None:
        super().close(); self._flush_line()


def parse_html_document(content:str,base_url:str="")->dict[str,object]:
    """Parse HTML into visible text lines and normalized outbound links."""
    if not isinstance(content,str): raise ValueError("HTML 内容必须是文本")
    if len(content)>20_000_000: raise ValueError("HTML 文本超过 20 MB 安全限制")
    parser=_VisibleParser(base_url)
    try: parser.feed(content); parser.close()
    except Exception as exc: raise ValueError(f"HTML 解析失败：{exc}") from exc
    title=_clean("".join(parser.title_parts)) or parser.og_title
    seen=set(); links=[]
    for item in parser.links:
        url=item["url"].split("#",1)[0]
        if url and url not in seen: seen.add(url); links.append({"text":item["text"],"url":url})
    lines=list(dict.fromkeys(line for line in parser.lines if line))
    if title and title not in lines: lines.insert(0,f"网页标题：{title}")
    if parser.description and parser.description not in lines: lines.insert(1 if title else 0,f"网页描述：{parser.description}")
    lines.extend(f"链接：{item['text'] or '(无链接文字)'} — {item['url']}" for item in links)
    return {"title":title,"description":parser.description,"lines":lines,"links":links}
