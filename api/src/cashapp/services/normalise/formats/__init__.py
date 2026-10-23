"""Media type to handler table: the one place formats are registered."""

from collections.abc import Mapping

from cashapp.domain.artifacts import UnsupportedReason
from cashapp.services.normalise import sniff
from cashapp.services.normalise.formats.archive import handle_zip
from cashapp.services.normalise.formats.docx import handle_docx
from cashapp.services.normalise.formats.images import handle_image_convert, handle_image_passthrough
from cashapp.services.normalise.formats.mime_email import handle_eml
from cashapp.services.normalise.formats.outlook_msg import handle_msg
from cashapp.services.normalise.formats.pdf import handle_pdf
from cashapp.services.normalise.formats.tables import handle_csv, handle_xlsx
from cashapp.services.normalise.formats.text import handle_html, handle_text
from cashapp.services.normalise.model import Handler, Item, Node, Reject, WalkContext


def _rejecting(reason: UnsupportedReason) -> Handler:
    def handler(item: Item, ctx: WalkContext) -> Node:
        raise Reject(reason, item.media_type)

    return handler


HANDLERS: Mapping[str, Handler] = {
    sniff.TEXT: handle_text,
    sniff.HTML: handle_html,
    sniff.CSV: handle_csv,
    sniff.XLSX: handle_xlsx,
    sniff.DOCX: handle_docx,
    sniff.PDF: handle_pdf,
    sniff.PNG: handle_image_passthrough,
    sniff.JPEG: handle_image_passthrough,
    sniff.TIFF: handle_image_convert,
    sniff.GIF: handle_image_convert,
    sniff.BMP: handle_image_convert,
    sniff.WEBP: handle_image_convert,
    sniff.EML: handle_eml,
    sniff.MSG: handle_msg,
    sniff.ZIP: handle_zip,
    sniff.EXE: _rejecting(UnsupportedReason.EXECUTABLE),
    sniff.OLE: _rejecting(UnsupportedReason.LEGACY_OFFICE),
    sniff.OCTET: _rejecting(UnsupportedReason.UNKNOWN_FORMAT),
}
