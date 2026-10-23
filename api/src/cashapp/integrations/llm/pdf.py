"""PDF to text plus images, for readers that cannot take a PDF directly.

No PDF rasteriser is installed, so a page is represented by its text layer (pypdf) and the images
embedded in it (a scanned page is one image). A vector-only page contributes text only; pages
that give neither are listed so the caller can say so.
"""

import io
import logging
from dataclasses import dataclass
from typing import Any

from pypdf import PdfReader

from cashapp.integrations.llm.base import ImagePart

logger = logging.getLogger(__name__)

_MODES_OK = frozenset({"RGB", "RGBA", "L", "LA"})


@dataclass(frozen=True, slots=True)
class PdfRendering:
    text: str
    images: tuple[ImagePart, ...]
    pages: int
    pages_without_content: tuple[int, ...]


def _png_bytes(raw: bytes) -> bytes | None:
    """Re-encode an embedded image as PNG; None when it cannot be decoded."""
    from PIL import Image  # deferred: Pillow is only needed on this path

    try:
        with Image.open(io.BytesIO(raw)) as image:
            image.load()
            converted: Any = image if image.mode in _MODES_OK else image.convert("RGB")
            out = io.BytesIO()
            converted.save(out, format="PNG")
            return out.getvalue()
    except Exception:  # undecodable embedded image: skip it, the page text may still be useful
        logger.debug("embedded pdf image skipped")
        return None


def pdf_to_text_and_images(
    data: bytes, *, max_pages: int = 30, max_images: int = 20
) -> PdfRendering:
    """Text layer per page and embedded page images as PNG, capped by pages and image count.

    Raises ``ValueError`` for a file that is not a readable PDF or is encrypted.
    """
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted and not reader.decrypt(""):
            raise ValueError("pdf is encrypted")
        total_pages = len(reader.pages)
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(f"unreadable pdf: {type(exc).__name__}") from exc

    chunks: list[str] = []
    images: list[ImagePart] = []
    empty_pages: list[int] = []
    for index in range(min(total_pages, max_pages)):
        page = reader.pages[index]
        page_no = index + 1
        try:
            page_text = (page.extract_text() or "").strip()
        except Exception:  # a damaged text layer must not lose the page images
            logger.debug("pdf page %d text layer unreadable", page_no)
            page_text = ""
        if page_text:
            chunks.append(f"[page {page_no}]\n{page_text}")
        page_has_image = False
        try:
            embedded = list(page.images)
        except Exception:
            logger.debug("pdf page %d images unreadable", page_no)
            embedded = []
        for image in embedded:
            if len(images) >= max_images:
                break
            png = _png_bytes(image.data)
            if png is not None:
                images.append(ImagePart(png, "image/png"))
                page_has_image = True
        if not page_text and not page_has_image:
            empty_pages.append(page_no)
    return PdfRendering(
        text="\n\n".join(chunks),
        images=tuple(images),
        pages=total_pages,
        pages_without_content=tuple(empty_pages),
    )
