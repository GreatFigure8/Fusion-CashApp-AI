"""Normalisation limits (defaults are the pinned production values)."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class NormalisationLimits:
    max_depth: int = 3  # nesting of zip/eml/msg containers below the top artifact
    max_total_bytes: int = 50 * 1024 * 1024  # cumulative expanded bytes across the tree
    max_archive_members: int = 500
    max_compression_ratio: int = 100  # per member, uncompressed / compressed
    max_image_frames: int = 50  # TIFF/GIF pages converted
    min_inline_image_bytes: int = 30_000  # cid-referenced inline image below this = decoration


DEFAULT_LIMITS = NormalisationLimits()
