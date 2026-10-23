"""Vocabulary of the in-depth review upload flow. Pure: no I/O, no framework imports."""

from enum import StrEnum
from typing import Final


class UploadStatus(StrEnum):
    STORED = "STORED"
    DUPLICATE = "DUPLICATE"
    TOO_LARGE = "TOO_LARGE"
    NOT_ALLOWED = "NOT_ALLOWED"
    QUOTA = "QUOTA"


class FieldSource(StrEnum):
    """Where the adjudicated value of a field came from."""

    A_EQ_B = "A_EQ_B"
    A_B_DIFFERED = "A_B_DIFFERED"
    A_ONLY = "A_ONLY"
    B_ONLY = "B_ONLY"


class SniffedType(StrEnum):
    PNG = "png"
    JPEG = "jpeg"
    WEBP = "webp"
    PDF = "pdf"


# The history reasoning marker the daily quota counts. Written by ingest for uploaded items.
RECEIVED_FOR_REVIEW: Final = "received for in-depth review"

SOURCE_REF_PREFIX: Final = "upload:"


def upload_source_ref(subject: str) -> str:
    return f"{SOURCE_REF_PREFIX}{subject}"


MEDIA_TYPES: Final = {
    SniffedType.PNG: "image/png",
    SniffedType.JPEG: "image/jpeg",
    SniffedType.WEBP: "image/webp",
    SniffedType.PDF: "application/pdf",
}
