"""PDF: the original bytes are kept; the text layer is extracted when present."""

import io

from pypdf import PageObject, PdfReader

from cashapp.domain.artifacts import NormalisedPart, PartKind, UnsupportedReason
from cashapp.services.normalise.model import Item, Leaf, Reject, WalkContext
from cashapp.services.normalise.sniff import PDF


def _page_text(page: PageObject) -> str:
    try:
        return str(page.extract_text() or "")
    except Exception:
        return ""


def handle_pdf(item: Item, ctx: WalkContext) -> Leaf:
    reader = PdfReader(io.BytesIO(item.data))
    if reader.is_encrypted:
        raise Reject(UnsupportedReason.ENCRYPTED_PDF, "encrypted")
    joined = "\f".join(_page_text(page) for page in reader.pages)
    text = joined if joined.strip(" \f\n\t\r") else None
    return Leaf([NormalisedPart(PartKind.PDF, PDF, item.data, item.path, text)])
