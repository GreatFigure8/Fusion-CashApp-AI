"""Artifact normalisation: any intake artifact to reader-ready candidate documents.

Pure and synchronous (CPU-bound): no I/O, no DB, no LLM. Call it from async code through
`await asyncio.to_thread(normalise, incoming)`.
"""

from cashapp.domain.artifacts import (
    CandidateDocument,
    IncomingArtifact,
    NormalisationResult,
    Normalised,
    NormalisedPart,
    PartKind,
    Unsupported,
    UnsupportedNote,
    UnsupportedReason,
)
from cashapp.services.normalise.assemble import assemble, document_hash
from cashapp.services.normalise.heuristics import body_looks_like_remittance
from cashapp.services.normalise.limits import DEFAULT_LIMITS, NormalisationLimits
from cashapp.services.normalise.sniff import OCTET
from cashapp.services.normalise.strip import strip_body
from cashapp.services.normalise.walker import Walker

__all__ = [
    "DEFAULT_LIMITS",
    "CandidateDocument",
    "IncomingArtifact",
    "NormalisationLimits",
    "NormalisationResult",
    "Normalised",
    "NormalisedPart",
    "PartKind",
    "Unsupported",
    "UnsupportedNote",
    "UnsupportedReason",
    "body_looks_like_remittance",
    "document_hash",
    "normalise",
    "strip_body",
]


def normalise(
    incoming: IncomingArtifact, *, limits: NormalisationLimits = DEFAULT_LIMITS
) -> NormalisationResult:
    """Normalise one artifact. Never raises for bad input; deterministic for the same bytes."""
    walker = Walker(limits)
    root = walker.walk(incoming.data, incoming.filename, incoming.content_type, incoming.filename)
    documents = assemble(root) if root is not None else []
    notes = list(walker.notes)
    if documents:
        return Normalised(documents=documents, unsupported=notes)
    reason = notes[0].reason if notes else UnsupportedReason.EMPTY
    return Unsupported(reason=reason, media_type=walker.first_media_type or OCTET, notes=notes)
