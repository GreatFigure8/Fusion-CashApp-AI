"""DOCX: the original is kept; paragraphs and tables (as TSV) are extracted in body order."""

import io

from docx import Document
from docx.table import Table

from cashapp.domain.artifacts import NormalisedPart, PartKind
from cashapp.services.normalise.model import Item, Leaf, WalkContext
from cashapp.services.normalise.sniff import DOCX


def _table_tsv(table: Table) -> str:
    rows = ["\t".join(" ".join(cell.text.split()) for cell in row.cells) for row in table.rows]
    return "\n".join(rows)


def handle_docx(item: Item, ctx: WalkContext) -> Leaf:
    document = Document(io.BytesIO(item.data))
    blocks: list[str] = []
    for block in document.iter_inner_content():
        text = _table_tsv(block) if isinstance(block, Table) else block.text
        if text.strip():
            blocks.append(text)
    extracted = "\n".join(blocks)
    return Leaf([NormalisedPart(PartKind.DOCX, DOCX, item.data, item.path, extracted or None)])
