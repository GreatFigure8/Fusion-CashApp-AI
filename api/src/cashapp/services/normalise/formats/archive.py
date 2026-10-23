"""Zip archives: bounded, header-distrusting, recursive."""

import io
import zipfile

from cashapp.domain.artifacts import UnsupportedReason
from cashapp.services.normalise.model import (
    Container,
    Item,
    Node,
    Reject,
    WalkContext,
    unique_name,
)
from cashapp.services.normalise.sniff import ZIP

_CHUNK = 64 * 1024
_ENCRYPTED_FLAG = 0x1


def _ignored(info: zipfile.ZipInfo) -> bool:
    name = info.filename
    return name.startswith("__MACOSX/") or name.rsplit("/", 1)[-1] == ".DS_Store"


def _check(infos: list[zipfile.ZipInfo], ctx: WalkContext) -> None:
    limits = ctx.limits
    if len(infos) > limits.max_archive_members:
        raise Reject(UnsupportedReason.ARCHIVE_TOO_LARGE, f"{len(infos)} members")
    if any(info.flag_bits & _ENCRYPTED_FLAG for info in infos):
        raise Reject(UnsupportedReason.ENCRYPTED_ARCHIVE, "password protected")
    for info in infos:
        if info.file_size > 0 and (
            info.compress_size == 0
            or info.file_size / info.compress_size > limits.max_compression_ratio
        ):
            raise Reject(UnsupportedReason.ARCHIVE_BOMB, "compression ratio over limit")
    if sum(info.file_size for info in infos) > ctx.remaining():
        raise Reject(UnsupportedReason.ARCHIVE_TOO_LARGE, "declared size over limit")


def _read_member(archive: zipfile.ZipFile, info: zipfile.ZipInfo, cap: int) -> bytes:
    """Read in bounded chunks; the declared size is not trusted."""
    buffer = bytearray()
    with archive.open(info) as handle:
        while chunk := handle.read(_CHUNK):
            buffer += chunk
            if len(buffer) > info.file_size:
                raise Reject(UnsupportedReason.ARCHIVE_BOMB, "member larger than declared")
            if len(buffer) > cap:
                raise Reject(UnsupportedReason.ARCHIVE_TOO_LARGE, "expanded size over limit")
    return bytes(buffer)


def handle_zip(item: Item, ctx: WalkContext) -> Container:
    children: list[Node] = []
    seen: set[str] = set()
    with zipfile.ZipFile(io.BytesIO(item.data)) as archive:
        infos = [info for info in archive.infolist() if not info.is_dir()]
        for info in infos:
            if _ignored(info):
                ctx.note(
                    f"{item.path}/{info.filename}",
                    ZIP,
                    UnsupportedReason.UNKNOWN_FORMAT,
                    "ignored by rule",
                )
        infos = [info for info in infos if not _ignored(info)]
        _check(infos, ctx)
        for info in infos:
            data = _read_member(archive, info, ctx.remaining())
            path = f"{item.path}/{unique_name(info.filename, seen)}"
            child = ctx.walk_child(data, info.filename, None, path, item.depth + 1)
            if child is not None:
                children.append(child)
    return Container(children)
