"""Media-type detection: magic bytes first, then declared type, then extension."""

import io
import re
import zipfile

PDF = "application/pdf"
PNG = "image/png"
JPEG = "image/jpeg"
GIF = "image/gif"
TIFF = "image/tiff"
BMP = "image/bmp"
WEBP = "image/webp"
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
ZIP = "application/zip"
EML = "message/rfc822"
MSG = "application/vnd.ms-outlook"
HTML = "text/html"
CSV = "text/csv"
TEXT = "text/plain"
EXE = "application/x-msdownload"
OLE = "application/x-ole-storage"
OCTET = "application/octet-stream"

_EXTENSIONS: dict[str, str] = {
    ".eml": EML,
    ".msg": MSG,
    ".csv": CSV,
    ".html": HTML,
    ".htm": HTML,
    ".txt": TEXT,
}
_DECLARED_TEXT = {EML, CSV, HTML, TEXT}
_MSG_MARKER = "__properties_version1.0".encode("utf-16-le")
_EML_HEADER = re.compile(
    r"^(?:from|received|mime-version|return-path):", re.IGNORECASE | re.MULTILINE
)
_HEADER_LINE = re.compile(r"^[A-Za-z][A-Za-z0-9-]*:|^[ \t]")
_HTML_START = re.compile(r"^\s*(?:<!doctype\s+html|<html)", re.IGNORECASE)
_CONTROL = frozenset(range(0, 32)) - {9, 10, 12, 13}


def _is_text(data: bytes) -> bool:
    return not any(b in _CONTROL for b in data[:4096])


def _decode_head(data: bytes) -> str:
    head = data[:8192]
    try:
        return head.decode("utf-8-sig")
    except UnicodeDecodeError:
        return head.decode("cp1252", errors="replace")


def _looks_like_eml(head: str) -> bool:
    block = head.replace("\r\n", "\n").split("\n\n", 1)[0]
    lines = [line for line in block.split("\n") if line]
    if not lines or not all(_HEADER_LINE.match(line) for line in lines):
        return False
    return _EML_HEADER.search(block) is not None


def _extension(filename: str) -> str:
    dot = filename.rfind(".")
    return filename[dot:].lower() if dot >= 0 else ""


def _sniff_zip(data: bytes) -> str:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            names = set(zf.namelist())
    except (zipfile.BadZipFile, OSError, ValueError):
        return ZIP
    if "word/document.xml" in names:
        return DOCX
    if "xl/workbook.xml" in names:
        return XLSX
    return ZIP


def _sniff_magic(data: bytes, ext: str) -> str | None:
    if data.startswith(b"%PDF-"):
        return PDF
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return PNG
    if data.startswith(b"\xff\xd8\xff"):
        return JPEG
    if data.startswith((b"GIF87a", b"GIF89a")):
        return GIF
    if data.startswith((b"II*\x00", b"MM\x00*")):
        return TIFF
    if data.startswith(b"BM") and ext == ".bmp":
        return BMP
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return WEBP
    if data.startswith(b"PK\x03\x04"):
        return _sniff_zip(data)
    if data.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"):
        return MSG if _MSG_MARKER in data or ext == ".msg" else OLE
    if data.startswith(b"MZ"):
        return EXE
    return None


def sniff_media_type(data: bytes, filename: str, declared: str | None) -> str:
    """Return the detected media type; OCTET when nothing fits."""
    if not data:
        return OCTET
    ext = _extension(filename)
    magic = _sniff_magic(data, ext)
    if magic is not None:
        return magic
    if not _is_text(data):
        return OCTET
    head = _decode_head(data)
    if _HTML_START.match(head):
        return HTML
    kind = (declared or "").split(";", 1)[0].strip().lower()
    if kind == EML or _looks_like_eml(head):
        return EML
    if kind in _DECLARED_TEXT:
        return kind
    return _EXTENSIONS.get(ext, TEXT)
