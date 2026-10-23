"""Plain text and HTML bodies."""

import re

from bs4 import BeautifulSoup, Tag
from bs4.element import Comment, NavigableString

from cashapp.domain.artifacts import PartKind, UnsupportedReason
from cashapp.services.normalise.model import Item, Leaf, Reject, WalkContext, text_part
from cashapp.services.normalise.sniff import HTML, TEXT

_BLOCK_TAGS = (
    "p", "div", "li", "tr", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "pre",
    "section", "article", "header", "footer", "hr",
)  # fmt: skip
_BLANKS = re.compile(r"\n{3,}")
_SPACES = re.compile(r"\s+")


def decode_text(data: bytes) -> str:
    """UTF-8 (BOM removed), falling back to cp1252; newlines normalised to LF."""
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = data.decode("cp1252", errors="replace")
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _cell_text(cell: Tag) -> str:
    return " ".join(cell.get_text(" ").split())


def _table_tsv(table: Tag) -> str:
    rows: list[str] = []
    for tr in table.find_all("tr"):
        if tr.find_parent("table") is not table:
            continue
        cells = [_cell_text(c) for c in tr.find_all(["td", "th"], recursive=False)]
        if any(cells):
            rows.append("\t".join(cells))
    return "\n".join(rows)


def html_to_text(html: str) -> str:
    """HTML to text: scripts and styles dropped, tables kept as TSV rows."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "head", "title"]):
        tag.decompose()
    for node in list(soup.find_all(string=True)):
        if isinstance(node, Comment):
            node.extract()
        else:
            node.replace_with(NavigableString(_SPACES.sub(" ", str(node))))
    for table in soup.find_all("table"):
        if table.find_parent("table") is None:
            table.replace_with(NavigableString(f"\n{_table_tsv(table)}\n"))
    for br in soup.find_all("br"):
        br.replace_with(NavigableString("\n"))
    for tag in soup.find_all(_BLOCK_TAGS):
        tag.insert_before(NavigableString("\n"))
        tag.insert_after(NavigableString("\n"))
    lines = [
        line.rstrip() if "\t" in line else line.strip() for line in soup.get_text().split("\n")
    ]
    return _BLANKS.sub("\n\n", "\n".join(lines)).strip()


def handle_text(item: Item, ctx: WalkContext) -> Leaf:
    text = decode_text(item.data)
    if not text.strip():
        raise Reject(UnsupportedReason.EMPTY, "blank text")
    return Leaf([text_part(PartKind.TEXT, TEXT, text, item.path)])


def handle_html(item: Item, ctx: WalkContext) -> Leaf:
    text = html_to_text(decode_text(item.data))
    if not text:
        raise Reject(UnsupportedReason.EMPTY, f"blank {HTML}")
    return Leaf([text_part(PartKind.TEXT, TEXT, text, item.path)])
