# s34-artifact-normalisation: Artifact normalisation (every format, one email with several remittances)

- Issue: #34
- Wave: 2 (owns `cashapp/services/normalise/`)
- breaking: false

## Story

As the readers downstream, I want each intake item turned into clean, reader-ready parts whatever the format, and an email holding several remittances split into several candidate documents, so that extraction sees one remittance at a time.

## Context

A pure function (no I/O, no DB): s06 calls it and persists the result. Originals are stored untouched by s06 before this runs. Libraries pinned in s01: stdlib `email`, extract-msg, pypdf, pillow, openpyxl, python-docx, beautifulsoup4, zipfile.

## Acceptance criteria

0. [unit] `cashapp/domain/artifacts.py` (owned here, imported by s06): `IncomingArtifact{source_kind, source_ref, filename, content_type, data: bytes, received_at, sender|None, subject|None}` and `PartKind`.
1. [unit] `normalise(incoming: IncomingArtifact) -> NormalisationResult` (`Normalised{documents: list[CandidateDocument]}` | `Unsupported{reason, media_type}`), `CandidateDocument{parts: list[NormalisedPart{kind: TEXT|PDF|IMAGE|TABLE|DOCX, media_type, data: bytes, source_path, text|None}], document_hash: str}`.
2. [unit] Handles: plain-text and HTML bodies (HTML → text via BeautifulSoup, tables preserved as TSV), PDF (kept as PDF part; text layer extracted into `text` when present), PNG/JPEG/TIFF/GIF (TIFF/GIF converted to PNG per page), XLSX and CSV (each sheet → TABLE part as CSV text), DOCX (text + tables), nested `.eml` and `.msg` (recursively), zip archives (recursively, depth ≤ 3, total ≤ 50 MB, zip-bomb guard). Each format has a fixture test.
3. [unit] Bodies have signatures, legal disclaimers and quoted reply chains stripped (`On … wrote:`, `-----Original Message-----`, `From:` header blocks, `>` quoting, common disclaimer markers); stripped text is never sent to readers but the original stays in Object Storage.
4. [unit] One email can yield several candidate documents: each attachment that is a standalone document (PDF, image, spreadsheet, DOCX, nested message) is its own candidate; the body is a candidate only if, after stripping, it contains ≥ 1 invoice-like token or an amount table (heuristic `body_looks_like_remittance`), otherwise it is attached as context TEXT part to every candidate. Test: an email with a body remittance and 2 PDF remittances yields 3 candidates; s06's integration test asserts 3 child items linked to the parent.
5. [unit] Unsupported formats (e.g. `.exe`, encrypted PDF, password zip, unknown binary) return `Unsupported{reason, media_type}`; mixed emails keep their supported parts and add a part-level `unsupported` note; nothing is silently dropped.
6. [unit] `document_hash` is the sha256 of the candidate's ordered part bytes (stable across runs).

## Out of scope

Classification of candidates (s07); persistence (s06).

## Deps

- s02-data-layer-foundation — `ErrorCode.UNSUPPORTED_ARTIFACT`. plannable.

## Assumptions

- `IncomingArtifact` lives in `cashapp/domain/artifacts.py` (owned here) so normalisation doesn't import the poller.
- One PDF containing several remittances stays one candidate; splitting inside a document is out of scope.
