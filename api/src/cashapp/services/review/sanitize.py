"""Pure byte functions that make an uploaded file safe to store and read. No I/O.

Nothing here trusts a declared type or a file name: the type comes from the bytes, image size comes
from the header alone (never a decode), and images lose their metadata and any bytes after the
image end losslessly, by removing whole segments or chunks instead of re-encoding.
"""

import io
import re
import struct
import warnings
from dataclasses import dataclass
from typing import Final

from PIL import Image
from pypdf import PdfReader

from cashapp.domain.review import SniffedType

_PNG_SIGNATURE: Final = b"\x89PNG\r\n\x1a\n"
_PDF_TRAILING_ALLOWANCE: Final = 1024
_PNG_DROP: Final = frozenset({b"eXIf", b"tEXt", b"iTXt", b"zTXt", b"tIME"})
_WEBP_DROP: Final = frozenset({b"EXIF", b"XMP "})
_WEBP_VP8X_METADATA_FLAGS: Final = 0x08 | 0x04  # EXIF and XMP present
_JPEG_DROP: Final = frozenset({0xE1, 0xED, 0xFE})  # APP1 (Exif, XMP), APP13 (IPTC), COM
_JPEG_STANDALONE: Final = frozenset({0x01, 0xD8, *range(0xD0, 0xD8)})
_PDF_ACTIVE: Final = re.compile(
    rb"/(?:JavaScript|JS|Launch|EmbeddedFile|OpenAction|AA|RichMedia|XFA)(?![A-Za-z0-9])"
)
_NAME_ESCAPE: Final = re.compile(rb"#([0-9A-Fa-f]{2})")


class MalformedFile(ValueError):  # noqa: N818 - pinned name
    """The bytes do not parse as the type they start with."""


@dataclass(frozen=True, slots=True)
class PdfVerdict:
    ok: bool
    reason: str | None = None
    pages: int | None = None


def sniff(head: bytes) -> SniffedType | None:
    """The file type from its leading bytes; ``None`` when it is not an allowed shape."""
    if head.startswith(_PNG_SIGNATURE):
        return SniffedType.PNG
    if head.startswith(b"\xff\xd8\xff"):
        return SniffedType.JPEG
    if len(head) >= 12 and head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return SniffedType.WEBP
    if head.startswith(b"%PDF-"):  # only at offset 0: a header later is a polyglot
        return SniffedType.PDF
    return None


def image_dimensions(data: bytes) -> tuple[int, int]:
    """Width and height read from the header only; the pixel data is never decoded."""
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as image:
                width, height = image.size
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise MalformedFile("image is too large") from exc
    except Exception as exc:  # Pillow raises many types for a damaged header
        raise MalformedFile("image header could not be read") from exc
    return width, height


def strip_image_metadata(data: bytes, kind: SniffedType) -> bytes:
    """The image without metadata or trailing bytes; the pixels are untouched."""
    if kind is SniffedType.JPEG:
        return _strip_jpeg(data)
    if kind is SniffedType.PNG:
        return _strip_png(data)
    if kind is SniffedType.WEBP:
        return _strip_webp(data)
    raise ValueError(f"not an image type: {kind}")


def _strip_jpeg(data: bytes) -> bytes:
    out = bytearray(data[:2])  # SOI
    pos = 2
    size = len(data)
    while pos < size:
        if data[pos] != 0xFF:
            raise MalformedFile("bad JPEG marker")
        while pos < size and data[pos] == 0xFF:  # fill bytes
            pos += 1
        if pos >= size:
            break
        marker = data[pos]
        pos += 1
        if marker == 0xD9:  # EOI: everything after it is dropped
            out += b"\xff\xd9"
            return bytes(out)
        if marker in _JPEG_STANDALONE:
            out += bytes((0xFF, marker))
            continue
        if pos + 2 > size:
            raise MalformedFile("truncated JPEG segment")
        (length,) = struct.unpack(">H", data[pos : pos + 2])
        if length < 2 or pos + length > size:
            raise MalformedFile("bad JPEG segment length")
        segment = data[pos : pos + length]
        pos += length
        if marker not in _JPEG_DROP:
            out += bytes((0xFF, marker)) + segment
        if marker == 0xDA:  # SOS: entropy-coded data follows up to the next real marker
            start = pos
            while pos + 1 < size:
                if data[pos] == 0xFF and data[pos + 1] not in (0x00, 0xFF, *range(0xD0, 0xD8)):
                    break
                pos += 1
            else:
                pos = size
            out += data[start:pos]
    raise MalformedFile("JPEG has no end marker")


def _strip_png(data: bytes) -> bytes:
    out = bytearray(_PNG_SIGNATURE)
    pos = len(_PNG_SIGNATURE)
    size = len(data)
    while pos + 12 <= size:
        (length,) = struct.unpack(">I", data[pos : pos + 4])
        end = pos + 12 + length
        if end > size:
            raise MalformedFile("truncated PNG chunk")
        kind = data[pos + 4 : pos + 8]
        if kind not in _PNG_DROP:
            out += data[pos:end]
        pos = end
        if kind == b"IEND":
            return bytes(out)
    raise MalformedFile("PNG has no end chunk")


def _strip_webp(data: bytes) -> bytes:
    if len(data) < 12:
        raise MalformedFile("truncated WEBP")
    (declared,) = struct.unpack("<I", data[4:8])
    limit = min(len(data), declared + 8)  # bytes after the RIFF payload are dropped
    pos = 12
    chunks = bytearray()
    while pos + 8 <= limit:
        fourcc = data[pos : pos + 4]
        (length,) = struct.unpack("<I", data[pos + 4 : pos + 8])
        end = pos + 8 + length + (length & 1)
        if pos + 8 + length > limit:
            raise MalformedFile("truncated WEBP chunk")
        end = min(end, limit)
        chunk = bytearray(data[pos:end])
        if fourcc == b"VP8X" and length >= 1:
            chunk[8] &= ~_WEBP_VP8X_METADATA_FLAGS & 0xFF
        if fourcc not in _WEBP_DROP:
            chunks += chunk
        pos = end
    return b"RIFF" + struct.pack("<I", 4 + len(chunks)) + b"WEBP" + bytes(chunks)


def inspect_pdf(data: bytes, max_pages: int) -> PdfVerdict:
    """Accept a plain, unencrypted PDF within the page limit; otherwise say why not."""
    try:
        reader = PdfReader(io.BytesIO(data), strict=True)
        if reader.is_encrypted:
            return PdfVerdict(False, "encrypted PDF")
        pages = len(reader.pages)
    except Exception:
        return PdfVerdict(False, "PDF could not be read")
    if pages > max_pages:
        return PdfVerdict(False, f"PDF has more than {max_pages} pages", pages)
    last_eof = data.rfind(b"%%EOF")
    if last_eof < 0 or len(data) - (last_eof + 5) > _PDF_TRAILING_ALLOWANCE:
        return PdfVerdict(False, "data after the end of the PDF", pages)
    plain = _NAME_ESCAPE.sub(lambda m: bytes([int(m.group(1), 16)]), data)
    if _PDF_ACTIVE.search(plain):
        return PdfVerdict(False, "PDF contains active or embedded content", pages)
    return PdfVerdict(True, None, pages)
