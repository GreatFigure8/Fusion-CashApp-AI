# failed-receipt-review: Upload failed receipt images for in-depth review

- Issue: #48 (AC 5)
- breaking: false
- Design screen owned: **Review** (`design/project/glass/Upload.dc.html`, design.md §3.6)

## Story

As an AR analyst, I want to drop one or more failed receipt images or PDFs and submit them for in-depth review, then see each one as a work item with its stored artifact and the review result, so that receipts the pipeline missed get a second, deeper read without leaving the app.

## Context

research.md a7: shared multi-file dropzone → thin Next route handler → new FastAPI multipart router (python-multipart already a dependency) → streamed size cap, magic-byte allowlist, pixel/page limits, EXIF strip → `ObjectStore` → existing `ingest()` with `SourceKind.MANUAL` (exists, `domain/work_item.py:11`) and the uploader's Principal; sha256 duplicate returns the existing item. In-depth review = the same stations at the configured high effort, no second code path; the review runs through the outbox, never inside the request. Risk notes: decompression bombs, polyglot/encrypted PDFs, prompt-injection text (reader prompts say artifact text is data). Keep each file within the Next proxy body limit: 5 MB per file. Load `python-library-quality:auditing-python-security`.

## Acceptance criteria

1. [unit] DB config keys owned here: `uploads.max_file_bytes` (5 MB), `uploads.max_files_per_request` (10), `uploads.daily_per_user` (20), `uploads.allowed_types` (png, jpeg, webp, pdf), `uploads.max_pixels`, `uploads.max_pdf_pages`, `review.effort` (reader and adjudicator effort for MANUAL items, default "high").
2. [unit] `cashapp/services/review/upload.py` `UploadService.submit(files, principal)`: per file, streamed size cap (stops reading past the cap), magic-byte sniff against the allowlist (declared type ignored), pixel and page limits checked before decode, encrypted or polyglot PDF refused, EXIF/location stripped from images, stored through `ObjectStore`, then `ingest()` with `SourceKind.MANUAL`, source_ref `upload:<user id>`, the uploader recorded on history; duplicate sha256 returns `{status: DUPLICATE, item_id}`. Results per file `{filename, status: STORED|DUPLICATE|TOO_LARGE|NOT_ALLOWED|QUOTA, item_id?, message}`; one bad file never fails the others.
3. [unit] Per-user daily quota (`uploads.daily_per_user`) enforced in the service, counted from history; the over-quota file returns `QUOTA`.
4. [unit] MANUAL items run the same stations; the extract and adjudicate stage runners read `review.effort` for MANUAL items (one effort lookup, no second path). Test: a MANUAL item's reader calls carry the high effort; a MAILBOX item's carry the normal one.
5. [api] New auto-discovered router `review.py`: `POST /review/uploads` (multipart, ITEMS_WORK) -> `UploadResultOut{files: [...], quota: {used, limit}}`; `GET /review/queue?offset=&limit=` (ITEMS_READ) -> MANUAL items with `{item_id, filename, stage, status, age, confidence?}`; `GET /review/quota` -> `{used, limit}`; `GET /review/items/{id}/result` -> `{fields: [{field, value, source: A_EQ_B|A_B_DIFFERED|A_ONLY|B_ONLY}], adjudication_note, confidence, applied: {receipt_number, lines, residual: MoneyStr} | null, preview: {artifact_key, page, region?}}`. OpenAPI regenerated.
6. [unit] Chat tool `review.submit` in `cashapp/services/chat/tools/review.py` (group REVIEW, mutating, confirm_required, ITEMS_WORK) takes upload ids staged by the chat attach (`POST /review/uploads?stage_only=true` returns `upload_ids` without ingesting) and calls `UploadService`; `review.queue` read tool.
7. [unit] `web/components/common/drop-zone.tsx` `DropZone{accept, maxBytes, maxFiles, onFiles, disabled}` is the one drop zone (owner: this story; assistant-chat-redesign's `+` attach imports it); `web/app/api/review/uploads/route.ts` is a thin streaming proxy with the user's token.
8. [browser] Review board: `/review` top bar "Review", env, Sample data, "Today N / M uploads"; glass upload panel with the dashed drop zone ("Drop failed receipt images", "PNG, JPG, WEBP or PDF · up to 5 MB each · 10 files at a time · location data is stripped", Choose files), thumbnails row (name, mono size, 4px progress bar, status pill Stored / Uploading N% / Duplicate of WI-… / Over 5 MB / Not an image), Clear and primary "Submit N for in-depth review".
9. [browser] Review board: Review queue table (Item, File, Stage mono, Status pill, Age; header "same stations · high effort") and the result panel for the selected item: preview through `common/artifact-viewer` with the highlighted amount region and caption, field table with source pills (`A = B` ok, `A, B differed` warn, `B only` muted), the adjudication note, the applied line, Open item / History links, header pill "<status> · <confidence>"; the panel updates live as the item moves.
10. [browser] Review board states: empty queue, loading result ("Both readers done, adjudicating…"), upload error ("<file> is over 5 MB. The other files were kept.").
11. [unit] The Review nav entry shows the open review-queue count from `/review/queue` total.

## Out of scope

- A second intake path or direct-to-bucket upload (research.md rejected a8/a9).

## Deps

- glass-theme-shell: `GlassPanel`, `Pill`, `Meter`, `DataTable`, `StateCard`, `TopBar`, nav count source in `nav.ts`. plannable: true.
- chat-agent-tool-registry: `ToolSpec`, `TOOLS` discovery, `ConfirmPreview`. plannable: true.
- db-stored-settings: `ConfigKey` spec and `RuntimeSettings` accessors for the new keys. plannable: true.
- live-progress-dashboard: `useEventStream` hook. plannable: true.

## Assumptions

- Upload permission is ITEMS_WORK (operators and admins), a plan-level decision design.md §9 left open.
- Staged chat uploads expire after 1 hour if not submitted (`uploads.stage_ttl_seconds`).
