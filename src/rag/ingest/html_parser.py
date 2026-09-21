"""HTML -> 结构化 Markdown 文本解析器（bs4，零额外依赖）。

对应设计方案 §4.2 的解析质量原则：
- 标题层级（h1-h6）→ Markdown 标题，供分块/面包屑使用；
- 表格 → Markdown 表格（表头 + 分隔行 + 行），**不丢表格内容**（答案常以表格承载）；
- 列表（ul/ol）→ 项目符号/编号行；
- 丢弃页面噪声：script/style/nav/footer/header 导航、aside、form、noscript 等，
  避免导航栏/版权信息进入知识内容；
- 链接保留文本（丢 href）；图片保留 alt（无 alt 则丢弃）；换行规范化。
"""
from __future__ import annotations

import re
import codecs

from bs4 import BeautifulSoup, Tag
from bs4.dammit import EncodingDetector


def decode_html(raw: bytes) -> str:
    """Decode without replacement characters that corrupt text and local image paths."""
    for bom, encoding in ((codecs.BOM_UTF32_LE, 'utf-32'),
                          (codecs.BOM_UTF32_BE, 'utf-32'),
                          (codecs.BOM_UTF16_LE, 'utf-16'),
                          (codecs.BOM_UTF16_BE, 'utf-16')):
        if raw.startswith(bom):
            return raw.decode(encoding, errors='strict')
    try:
        return raw.decode('utf-8-sig', errors='strict')
    except UnicodeDecodeError:
        declared = EncodingDetector.find_declared_encoding(raw, is_html=True)
        encoding = codecs.lookup(declared or 'gb18030').name
        if encoding in ('gb2312', 'gbk'):
            encoding = 'gb18030'
        return raw.decode(encoding, errors='strict')

# 页面噪声容器：整块丢弃（不提取其中文本）
_NOISE_TAGS = {
    "script", "style", "noscript", "iframe", "nav", "footer", "aside",
    "form", "button", "select", "input", "textarea", "svg", "canvas",
    "template", "dialog", "menu", "menuitem",
}
# 内容容器（避免 p 包裹 h 时重复输出）
_BLOCK_TAGS = {"p", "div", "section", "article", "main", "li", "td", "th", "caption", "blockquote", "pre", "figcaption"}

_WS = re.compile(r"[ \t\u00a0]+")
_MULTI_NL = re.compile(r"\n{3,}")


def _text(el) -> str:
    """提取元素文本并压缩空白。"""
    s = _WS.sub(" ", el.get_text(" ", strip=False))
    return s.strip()


def _table_to_markdown(table: Tag) -> str:
    """表格 -> Markdown 表格。第一行作为表头，生成分隔行。"""
    rows: list[list[str]] = []
    for tr in table.find_all("tr", recursive=True):
        cells = [c.get_text(" ", strip=True) for c in tr.find_all(["th", "td"], recursive=True)]
        if cells and any(cells):
            rows.append(cells)
    if not rows:
        return ""
    # 表头：首个含 th 的行，或第一行
    header = rows[0]
    body = rows[1:]
    n = max(len(r) for r in rows)
    header = header + [""] * (n - len(header))
    body = [r + [""] * (n - len(r)) for r in body]
    lines = ["| " + " | ".join(header) + " |"]
    lines.append("| " + " | ".join(["---"] * n) + " |")
    for r in body:
        lines.append("| " + " | ".join(r) + " |")
    return "\n".join(lines)


def _walk(el: Tag, out: list[str]) -> None:
    """深度遍历：按语义输出 Markdown 片段。"""
    if isinstance(el, Tag):
        name = el.name.lower()
        if name in _NOISE_TAGS:
            return
        if name in ("h1", "h2", "h3", "h4", "h5", "h6"):
            level = int(name[1])
            txt = _text(el)
            if txt:
                out.append(f"{'#' * level} {txt}")
            return
        if name == "table":
            md = _table_to_markdown(el)
            if md:
                out.append(md)
            return
        if name == "ul":
            for i, li in enumerate(el.find_all("li", recursive=False)):
                out.append(f"- {_text(li)}")
            return
        if name == "ol":
            for i, li in enumerate(el.find_all("li", recursive=False), start=1):
                out.append(f"{i}. {_text(li)}")
            return
        if name == "br":
            out.append("")
            return
        if name == "hr":
            out.append("---")
            return
        if name == "img":
            alt = el.get("alt", "").strip()
            if alt:
                out.append(f"[图片：{alt}]")
            return
        if name == "a":
            txt = _text(el)
            if txt:
                out.append(txt)
            return
        # 容器/行内标签：递归子节点
        for child in el.children:
            if isinstance(child, Tag):
                _walk(child, out)
            else:
                txt = str(child).strip()
                if txt:
                    out.append(txt)
        return
    txt = str(el).strip()
    if txt:
        out.append(txt)


def html_to_markdown(html: str, image_handler=None) -> str:
    """HTML 文档 -> 结构化 Markdown 文本（供分块/向量化）。"""
    soup = BeautifulSoup(html, "lxml")
    if image_handler is not None:
        for tag in soup.find_all('img'):
            if any(parent.name in _NOISE_TAGS for parent in tag.parents):
                continue
            replacement = soup.new_tag('span')
            replacement.string = image_handler(tag)
            tag.replace_with(replacement)
    out: list[str] = []

    title = soup.title.get_text(strip=True) if soup.title else ""
    if title:
        out.append(f"# {title}")

    body = soup.body if soup.body else soup
    _walk(body, out)

    # 规范化：压缩连续空行
    text = "\n".join(out)
    text = _MULTI_NL.sub("\n\n", text)
    return text.strip()
