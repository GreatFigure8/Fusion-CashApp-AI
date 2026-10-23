"""Images: PNG/JPEG pass through; TIFF/GIF/BMP/WEBP become one PNG per frame."""

import io

from PIL import Image, ImageSequence

from cashapp.domain.artifacts import NormalisedPart, PartKind, UnsupportedReason
from cashapp.services.normalise.model import Item, Leaf, Reject, WalkContext
from cashapp.services.normalise.sniff import PNG

_PNG_MODES = frozenset({"1", "L", "LA", "P", "RGB", "RGBA", "I;16"})


def _open(data: bytes) -> Image.Image:
    try:
        return Image.open(io.BytesIO(data))
    except Image.DecompressionBombError as exc:
        raise Reject(UnsupportedReason.ARCHIVE_BOMB, "image too large") from exc


def handle_image_passthrough(item: Item, ctx: WalkContext) -> Leaf:
    with _open(item.data) as image:
        image.verify()
    return Leaf([NormalisedPart(PartKind.IMAGE, item.media_type, item.data, item.path, None)])


def handle_image_convert(item: Item, ctx: WalkContext) -> Leaf:
    parts: list[NormalisedPart] = []
    limit = ctx.limits.max_image_frames
    with _open(item.data) as image:
        for number, frame in enumerate(ImageSequence.Iterator(image), start=1):
            if number > limit:
                ctx.note(
                    item.path,
                    item.media_type,
                    UnsupportedReason.ARCHIVE_TOO_LARGE,
                    "frames over limit",
                )
                break
            rendered = frame.copy()
            if rendered.mode not in _PNG_MODES:
                rendered = rendered.convert("RGB")
            buffer = io.BytesIO()
            rendered.save(buffer, format="PNG")
            parts.append(
                NormalisedPart(
                    PartKind.IMAGE, PNG, buffer.getvalue(), f"{item.path}#frame={number}", None
                )
            )
    if not parts:
        raise Reject(UnsupportedReason.EMPTY, "no frames")
    return Leaf(parts)
