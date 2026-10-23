"""Builds the synthetic artifact fixtures in this directory. Deterministic; outputs are committed.

Run once: ``python api/tests/fixtures/artifacts/build_fixtures.py``. Payer "Example Payer Co",
invoices INV-10001 and up. Nothing here is derived from a real customer.

``remittance.msg`` is not produced: no Outlook MSG writer is in the dependency set, so s34's .msg
test skips with that reason.
"""

import csv
import io
import struct
import zipfile
import zlib
from datetime import UTC, datetime
from email.message import EmailMessage
from email.utils import format_datetime
from pathlib import Path

import openpyxl
from docx import Document
from PIL import Image, ImageDraw
from pypdf import PdfReader, PdfWriter

OUT = Path(__file__).resolve().parent
SENT = datetime(2026, 1, 15, 9, 30, tzinfo=UTC)

LINES = [("INV-10001", "1500.00"), ("INV-10002", "820.50"), ("INV-10003", "99.99")]
BODY = (
    "Hello,\n\nPayment advice from Example Payer Co, paid 2026-01-14 by EFT,"
    " reference EP-20260114.\n\n"
    "Invoice      Amount\n"
    + "".join(f"{inv}    {amt}\n" for inv, amt in LINES)
    + "\nTotal 2420.49 USD\n"
)


def _message(subject: str, body: str, *, html: str | None = None) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = "ap@example-payer.test"
    msg["To"] = "cash@example-receiver.test"
    msg["Subject"] = subject
    msg["Date"] = format_datetime(SENT)
    msg["Message-ID"] = f"<{zlib.crc32(subject.encode())}@example-payer.test>"
    msg.set_content(body)
    if html is not None:
        msg.add_alternative(html, subtype="html")
    return msg


def _write(name: str, data: bytes) -> bytes:
    (OUT / name).write_bytes(data)
    return data


def text_pdf(lines: list[str]) -> bytes:
    """A one-page PDF with a text layer, written by hand."""
    stream = "BT /F1 12 Tf 50 750 Td 14 TL " + " ".join(f"({line}) '" for line in lines) + " ET"
    objects = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        "/Resources << /Font << /F1 5 0 R >> >> >>",
        f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets: list[int] = []
    for number, body in enumerate(objects, start=1):
        offsets.append(out.tell())
        out.write(f"{number} 0 obj\n{body}\nendobj\n".encode("latin-1"))
    xref = out.tell()
    out.write(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode("ascii"))
    for offset in offsets:
        out.write(f"{offset:010d} 00000 n \n".encode("ascii"))
    out.write(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode(
            "ascii"
        )
    )
    return out.getvalue()


def remittance_image(size: tuple[int, int] = (640, 360)) -> Image.Image:
    image = Image.new("RGB", size, "white")
    draw = ImageDraw.Draw(image)
    draw.text((20, 20), "Example Payer Co - remittance advice", fill="black")
    for row, (inv, amt) in enumerate(LINES):
        draw.text((20, 60 + 24 * row), f"{inv}   {amt}", fill="black")
    return image


def image_bytes(fmt: str, **kwargs: object) -> bytes:
    buffer = io.BytesIO()
    remittance_image().save(buffer, format=fmt, **kwargs)  # type: ignore[arg-type]
    return buffer.getvalue()


def zip_bytes(members: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in members.items():
            info = zipfile.ZipInfo(name, date_time=(2026, 1, 15, 9, 30, 0))
            archive.writestr(info, data)
    return buffer.getvalue()


def set_encryption_flag(data: bytes) -> bytes:
    """Set general-purpose bit 0 on every zip header: marks the members as password protected."""
    patched = bytearray(data)
    for signature, flag_offset in ((b"PK\x03\x04", 6), (b"PK\x01\x02", 8)):
        position = patched.find(signature)
        while position != -1:
            flags = struct.unpack_from("<H", patched, position + flag_offset)[0]
            struct.pack_into("<H", patched, position + flag_offset, flags | 0x1)
            position = patched.find(signature, position + 4)
    return bytes(patched)


def main() -> None:
    pdf_lines = ["Example Payer Co remittance", *(f"{inv} {amt}" for inv, amt in LINES)]
    remit_pdf = text_pdf(pdf_lines)
    other_pdf = text_pdf(["Example Payer Co remittance 2", "INV-10004 310.00", "INV-10005 45.10"])

    _write("remittance_body.eml", _message("Payment advice", BODY).as_bytes())

    rows = "".join(f"<tr><td>{inv}</td><td>{amt}</td></tr>" for inv, amt in LINES)
    head = "<tr><th>Invoice</th><th>Amount</th></tr>"
    html = f"<html><body><p>Payment advice</p><table>{head}{rows}</table></body></html>"
    _write(
        "remittance_html.eml",
        _message("Payment advice (html)", "See attached table.", html=html).as_bytes(),
    )

    two = _message("Payment advice with attachments", BODY)
    two.add_attachment(
        remit_pdf, maintype="application", subtype="pdf", filename="remittance_1.pdf"
    )
    two.add_attachment(
        other_pdf, maintype="application", subtype="pdf", filename="remittance_2.pdf"
    )
    _write("body_plus_two_pdfs.eml", two.as_bytes())

    inner = _message("Fwd: Payment advice", BODY)
    outer = _message("Forwarded remittance", "Please see the forwarded message.")
    outer.add_attachment(
        inner.as_bytes(), maintype="message", subtype="rfc822", filename="inner.eml"
    )
    _write("forwarded_nested.eml", outer.as_bytes())

    _write(
        "newsletter.eml",
        _message("Our January newsletter", "News and offers. No payment details here.").as_bytes(),
    )

    _write("remittance_text.pdf", remit_pdf)

    scan = io.BytesIO()
    remittance_image().save(scan, format="PDF")
    _write("remittance_scan.pdf", scan.getvalue())

    writer = PdfWriter(clone_from=PdfReader(io.BytesIO(remit_pdf)))
    writer.encrypt("secret")
    locked = io.BytesIO()
    writer.write(locked)
    _write("encrypted.pdf", locked.getvalue())

    _write("remittance.png", image_bytes("PNG"))
    _write("remittance.jpg", image_bytes("JPEG"))
    _write("remittance.gif", image_bytes("GIF"))
    pages = [remittance_image(), remittance_image((640, 400))]
    tiff = io.BytesIO()
    pages[0].save(tiff, format="TIFF", save_all=True, append_images=pages[1:])
    _write("remittance_multipage.tiff", tiff.getvalue())

    book = openpyxl.Workbook()
    first = book.active
    assert first is not None
    first.title = "Remittance"
    first.append(["Invoice", "Amount"])
    for inv, amt in LINES:
        first.append([inv, float(amt)])
    second = book.create_sheet("Notes")
    second.append(["Payer", "Example Payer Co"])
    xlsx = io.BytesIO()
    book.save(xlsx)
    _write("remittance.xlsx", xlsx.getvalue())

    text = io.StringIO()
    csv.writer(text, lineterminator="\n").writerows([["Invoice", "Amount"], *LINES])
    csv_bytes = _write("remittance.csv", text.getvalue().encode("utf-8"))

    doc = Document()
    doc.add_paragraph("Payment advice from Example Payer Co")
    table = doc.add_table(rows=1, cols=2)
    table.rows[0].cells[0].text = "Invoice"
    table.rows[0].cells[1].text = "Amount"
    for inv, amt in LINES:
        cells = table.add_row().cells
        cells[0].text = inv
        cells[1].text = amt
    docx = io.BytesIO()
    doc.save(docx)
    _write("remittance.docx", docx.getvalue())

    bundle = _write(
        "bundle.zip", zip_bytes({"remittance.pdf": remit_pdf, "remittance.csv": csv_bytes})
    )
    nested = _write("nested.zip", zip_bytes({"inner.zip": bundle}))
    deep = zip_bytes({"remittance.csv": csv_bytes})
    for level in range(3):
        deep = zip_bytes({f"level{level}.zip": deep})
    _write("too_deep.zip", deep)
    _write("password.zip", set_encryption_flag(zip_bytes({"remittance.csv": csv_bytes})))
    assert nested

    _write("unknown.bin", bytes(range(256)) * 4)
    _write("program.exe", b"MZ" + b"\x90\x00\x03\x00" + b"\x00" * 60)


if __name__ == "__main__":
    main()
