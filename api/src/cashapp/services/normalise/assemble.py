"""Turn a walk tree into candidate documents (one email can yield several)."""

import hashlib
from collections.abc import Sequence

from cashapp.domain.artifacts import CandidateDocument, NormalisedPart, PartKind
from cashapp.services.normalise.heuristics import body_looks_like_remittance
from cashapp.services.normalise.model import Container, EmailNode, Leaf, Node, text_part
from cashapp.services.normalise.sniff import TEXT


def document_hash(parts: Sequence[NormalisedPart]) -> str:
    """sha256 over the non-context parts in order, each framed by an 8-byte big-endian length."""
    digest = hashlib.sha256()
    for part in parts:
        if part.is_context:
            continue
        digest.update(len(part.data).to_bytes(8, "big"))
        digest.update(part.data)
    return digest.hexdigest()


def _candidates(node: Node) -> list[list[NormalisedPart]]:
    if isinstance(node, Leaf):
        return [list(node.parts)]
    if isinstance(node, Container):
        return [c for child in node.children for c in _candidates(child)]
    return _email_candidates(node)


def _email_candidates(node: EmailNode) -> list[list[NormalisedPart]]:
    attachments = [c for child in node.children for c in _candidates(child)]
    if not node.stripped:
        return attachments
    if body_looks_like_remittance(node.stripped) or not attachments:
        body = text_part(PartKind.TEXT, TEXT, node.text, f"{node.path}#body")
        return [[body], *attachments]
    context = text_part(PartKind.TEXT, TEXT, node.text, f"{node.path}#context", is_context=True)
    return [[*parts, context] for parts in attachments]


def assemble(root: Node) -> list[CandidateDocument]:
    return [CandidateDocument(parts, document_hash(parts)) for parts in _candidates(root)]
