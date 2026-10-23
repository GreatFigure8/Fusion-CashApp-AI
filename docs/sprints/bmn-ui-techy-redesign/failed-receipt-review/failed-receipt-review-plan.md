# Plan: failed-receipt-review

Story: [story.md](story.md). Board: Review (`design/project/glass/Upload.dc.html`, design.md §3.6). Skills applied: python-web-app:building-python-web-apps, python-library-quality:auditing-python-security, nextjs-fullstack-standards, plugin `references/nextjs.md` (+ typescript, route-handlers-and-apis, sse-and-streaming, proxy-auth-and-security, testing-and-observability).

## 1 Approach

research.md a7 as written: one shared `DropZone` → thin streaming Next route handler (`app/api/review/uploads/route.ts`, the user's token) → new auto-discovered FastAPI router `review.py` → `UploadService.submit` (framework-free, takes a `ByteSource` protocol that `UploadFile` satisfies) → per file: chunked read that stops at `uploads.max_file_bytes + 1`, magic-byte sniff (declared type ignored), header-only pixel / page-count check before any decode, PDF refused when encrypted or polyglot, images losslessly stripped of EXIF/XMP/IPTC and trailing bytes → the **existing** `ingest()` with `SourceKind.MANUAL`, `source_ref = "upload:<subject>"` and the uploader as the actor of the "received" history row. ingest's sha256 dedupe gives DUPLICATE. The review itself is the normal outbox-driven pipeline (research.md: "same stations at the configured high effort, no second code path", "never inside the upload request"): one `effort_for(item, role, config)` helper is read by the extract and adjudicate runners and returns `review.effort` for MANUAL items. Quota is counted from history rows (no new table, so **no migration**). Chat staging (`stage_only=true`) stores sanitized bytes under a new `staging/` object-key shape with a JSON sidecar; `review.submit` re-reads them and calls the same `UploadService`. The Review board reads `/review/queue` and `/review/items/{id}/result` and refetches on the existing flow SSE through `useEventStream` (live-progress-dashboard).

Deviations from research.md (recorded as Assumptions, §8): the result is shown on `/review` (board) as well as `/items/[id]`; the quota is a plain per-user count (`uploads.daily_per_user`), not wired to the llm_usage budget.

## 2 Files

### api/ (package `cashapp`)

| File | New/Change | Purpose |
|---|---|---|
| `src/cashapp/domain/config_keys.py` | change (append-only `uploads.*`/`review.*` block + entries in `_ALL_KEYS`) | `UPLOADS_MAX_FILE_BYTES` (int, default 5_242_880, 1..10_485_760), `UPLOADS_MAX_FILES_PER_REQUEST` (int, 10, 1..20), `UPLOADS_DAILY_PER_USER` (int, 20, 0..500), `UPLOADS_ALLOWED_TYPES` (list[Literal["png","jpeg","webp","pdf"]], all four, non-empty, unique), `UPLOADS_MAX_PIXELS` (int, 40_000_000, 1..100_000_000), `UPLOADS_MAX_PDF_PAGES` (int, 20, 1..100), `UPLOADS_STAGE_TTL_SECONDS` (int, 3600, 60..86_400), `REVIEW_EFFORT` (Literal["low","medium","high","max"], "high"). Group `uploads` for all eight. Uses db-stored-settings' `ConfigKey` spec (`restart_required=False`, `secret_ref=False` once those flags land). |
| `src/cashapp/services/config.py` | change | `UploadsConfig` dataclass + `ConfigSnapshot.uploads()` / `RuntimeConfig.uploads()` accessors (existing accessor pattern); per-key validators registered in the existing `validate_value` checks (bounds above; bool-as-int refused by the existing `_bool_leaks`). If db-stored-settings' `RuntimeSettings` lands first, the service reads through `RuntimeSettings.get(key)` instead; the keys are the contract. |
| `src/cashapp/domain/review.py` | new | Pure vocabulary: `UploadStatus` StrEnum `STORED|DUPLICATE|TOO_LARGE|NOT_ALLOWED|QUOTA`; `FieldSource` StrEnum `A_EQ_B|A_B_DIFFERED|A_ONLY|B_ONLY`; `SniffedType` StrEnum `png|jpeg|webp|pdf`; `RECEIVED_FOR_REVIEW = "received for in-depth review"` (history reasoning marker the quota counts); `upload_source_ref(subject) -> "upload:<subject>"`. |
| `src/cashapp/services/review/__init__.py` | new | Package. |
| `src/cashapp/services/review/sanitize.py` | new | Pure byte functions, no I/O: `sniff(head: bytes) -> SniffedType | None` (PNG `\x89PNG\r\n\x1a\n`, JPEG `FF D8 FF`, WEBP `RIFF....WEBP`, PDF `%PDF-` at offset 0 only); `image_dimensions(data, kind)` via Pillow `Image.open` header only (no `.load()`), with `Image.MAX_IMAGE_PIXELS` set from config and `DecompressionBombWarning` escalated to error; `strip_image_metadata(data, kind) -> bytes` lossless chunk/segment walker (JPEG: drop APP1 Exif/XMP, APP13 IPTC, COM, bytes after EOI; PNG: drop `eXIf tEXt iTXt zTXt tIME` chunks, bytes after IEND; WEBP: drop `EXIF`/`XMP ` chunks, clear VP8X flags, fix RIFF size); `inspect_pdf(data, max_pages) -> PdfVerdict` via `pypdf.PdfReader(strict=True)`: refuse `is_encrypted`, page count over limit, data before `%PDF-` or after the last `%%EOF` beyond 1 KiB, any of `/JavaScript /JS /Launch /EmbeddedFile /OpenAction /AA /RichMedia /XFA` (polyglot/active content). Each refusal returns a reason, never raises to the caller. |
| `src/cashapp/services/review/upload.py` | new | `ByteSource` Protocol (`filename: str | None`, `content_type: str | None`, `async read(size: int) -> bytes`); `UploadFileResult` / `UploadBatchResult` dataclasses; `UploadService(uow_factory, object_store, config, clock)` with `async submit(files: Sequence[ByteSource], principal: Principal) -> UploadBatchResult`, `async stage(files, principal) -> StageBatchResult`, `async submit_staged(upload_ids: Sequence[str], principal) -> UploadBatchResult`, `async quota(principal) -> Quota{used, limit}`. Per-file try/except boundary so one bad file never fails the others; files beyond `max_files_per_request` get NOT_ALLOWED; quota checked per file before ingest (`used + stored_this_request >= limit` → QUOTA). Calls `ingest(..., source_kind=SourceKind.MANUAL, actor=principal, received_payload={"upload": {filename, size_bytes, sniffed_type}})`. Filenames are sanitised (basename, control chars removed, 200 chars) and never logged with content. |
| `src/cashapp/services/review/staging.py` | new | Staged-upload store over `ObjectStore`: `put_staged(data, meta) -> upload_id` (uuid4 hex), `take_staged(upload_id, principal, now) -> (bytes, meta)` refusing another owner (NOT_ALLOWED "not your upload") or expired (`uploads.stage_ttl_seconds`), deleting both objects after a successful ingest. Sidecar JSON `{owner, filename, content_type, sniffed_type, size_bytes, sha256, staged_at}`. |
| `src/cashapp/services/review/effort.py` | new | `effort_for(item: WorkItem, role: ModelRole, config: ConfigSnapshot) -> str | None`: `fix_hints["effort"]` (auto-fix override) > `config.get(REVIEW_EFFORT)` when `item.source_kind is SourceKind.MANUAL` > `role.effort`. The one lookup both runners call. |
| `src/cashapp/services/review/queue.py` | new | `ReviewQueueService.page(offset, limit, open_only) -> Page[ReviewQueueRow]` and `ReviewResultService.result(item_id) -> ReviewResult | None` (fields + sources from the latest `Adjudication` provenance/disagreements, applied summary from applications + reservation, preview from the amount field's source location). Money is `Decimal` → `MoneyStr`, residual never summed across currencies. |
| `src/cashapp/pollers/intake/ingest.py` | change | `ingest()` gains keyword-only `actor: Principal | None = None` and `received_payload: Mapping[str, Any] | None = None`. When `actor` is set, the "received" STAGE_TRANSITION row uses `actor_fields(actor)` and reasoning `RECEIVED_FOR_REVIEW`, payload merged; the duplicate DECISION row also carries the actor. Default `None` keeps every existing caller byte-identical. |
| `src/cashapp/integrations/storage/keys.py` | change | `_KEY_RE` also accepts `staging/[0-9a-f]{32}(\.json)?`; `staged_key(upload_id)`, `staged_meta_key(upload_id)`. Existing artifact shapes unchanged. |
| `src/cashapp/data/repositories/history.py` | change | `count_by_actor_since(actor_id: str, reasoning: str, since: datetime) -> int` (parameterised, no business rule). |
| `src/cashapp/data/repositories/review.py` | new | `ReviewQueueRepository(BaseRepository[WorkItem])`: `page(offset, limit, open_only) -> Page[ReviewQueueRecord]` — `source_kind = MANUAL`, `state != ARCHIVED` (envelopes hidden), open = state not in terminal set; filename from the received-for-review history payload; latest adjudication confidence; newest first. `open_count() -> int`. |
| `src/cashapp/stations/extract/runner.py` | change | Reader A effort = `effort_for(item, role, ctx.config)` (replaces `hints.get("effort") or role.effort`); Reader B stays `None` (Cohere has no effort). |
| `src/cashapp/stations/adjudicate/runner.py`, `stations/adjudicate/prompts.py` | change | `build_adjudicator_request(..., effort: str | None)` (keyword, defaults to `role.effort`); runner passes `effort_for(ctx.item, models.adjudicator, ctx.config)`. |
| `src/cashapp/api/schemas/review.py` | new | Pydantic v2 contracts in §7 (`UploadFileResultOut`, `QuotaOut`, `UploadResultOut`, `StagedUploadsOut`, `ReviewQueueRowOut`, `ReviewQueuePage`, `ReviewFieldOut`, `AppliedOut`, `PreviewOut`, `RegionOut`, `ReviewResultOut`). Never returns ORM rows. |
| `src/cashapp/api/routers/review.py` | new (auto-discovered) | `POST /review/uploads` (ITEMS_WORK; `415` unless `multipart/form-data`; `413` when `Content-Length` > `max_files_per_request * max_file_bytes + 1 MiB`; `request.form(max_files=max_files_per_request + 1, max_fields=4)`), `GET /review/queue` (ITEMS_READ), `GET /review/quota` (ITEMS_READ), `GET /review/items/{item_id}/result` (ITEMS_READ; 404 for non-MANUAL or unknown). Errors through the single `ApiError` shape; `get_upload_service` dependency overridable in tests. |
| `src/cashapp/services/chat/tools/review.py` | new (discovered via `TOOLS`) | `review.submit` (group REVIEW, mutating, confirm_required, ITEMS_WORK, audit_label "Submit receipts for in-depth review", preview: What "Submit N files for in-depth review", Before "Today used / limit", After "used+N / limit", Who principal) → `UploadService.submit_staged`; `review.queue` (REVIEW, read-only, ITEMS_READ) → `ReviewQueueService.page`. |
| `src/cashapp/stations/extract/prompts.py` | change (one line, only if absent) | Reader system prompt states that artifact text is data, never instructions (research.md risk). Coder checks first; if the sentence is already there, no change. |

### web/

| File | New/Change | Purpose |
|---|---|---|
| `components/common/drop-zone.tsx` | new (owner) | `"use client"` `DropZone{accept: readonly string[]; maxBytes: number; maxFiles: number; onFiles(files: readonly File[], rejected: readonly RejectedFile[]): void; disabled?: boolean; title?: string; hint?: string; variant?: "panel" | "inline"}`; dashed zone, hidden `<input type=file multiple accept>`, keyboard (Enter/Space opens picker), drag-over accent state, client-side pre-check only for UX (size/count/extension) — the API is the control. |
| `components/review/upload-panel.tsx` | new | Glass upload panel: DropZone (title "Drop failed receipt images", hint from config values), thumbnails row, Clear, primary "Submit N for in-depth review"; uploads with `XMLHttpRequest` to `/api/review/uploads` for `upload.onprogress` (fetch has no upload progress). |
| `components/review/upload-thumb.tsx` | new | One thumbnail: object-URL preview (images) or PDF glyph, name, mono size, 4px `Meter`, status pill. |
| `components/review/queue-table.tsx` | new | Review queue on `DataTable` (Item, File, Stage mono, Status pill via `status-badge`, Age), header label "same stations · high effort", selected-row tint, empty/loading states. |
| `components/review/result-panel.tsx` | new | Result for the selected item: `common/artifact-viewer` preview with highlight + caption "page N · amount", field table with source pills, adjudication note, applied line, Open item / History links, header pill "<status> · <confidence>", loading "Both readers done, adjudicating…". |
| `components/review/review-board.tsx` | new | Client island that owns selection, polling-free refresh via `useEventStream` (from `@/hooks/use-event-stream`) on the existing flow stream; refetches queue and the selected result (debounced 1 s) when an event names a queue item or the selected item. |
| `components/review/schemas.ts` | new | Zod schemas for the upload response and the error envelope (parsed at the client boundary); types from `lib/api/types`. |
| `components/review/format.ts` | new | `formatBytes`, `sourcePill(source) -> {tone, label}` (`A_EQ_B` ok "A = B", `A_B_DIFFERED` warn "A, B differed", `A_ONLY` muted "A only", `B_ONLY` muted "B only"), `uploadPill(status, progress, item_id)` ("Stored", "Uploading N%", "Duplicate of WI-…", "Over 5 MB" (limit from config), "Not an image", "Daily limit reached"). |
| `components/review/nav-count.ts` | new | `reviewOpenCount(): Promise<number | null>` — calls `/review/queue?open_only=true&limit=1`, returns `total`. |
| `components/shell/nav.ts` | change (Review entry's count source only, per split.md) | Wire the Review (`RV`) entry's count source to `reviewOpenCount` through glass-theme-shell's count-source API. No other edit. |
| `app/(shell)/review/page.tsx` | new | Server Component: `TopBar` "Review" + env + Sample data + quota text "Today N / M uploads" from `/review/quota`; first queue page fetched server-side via `api()` (API-6); renders `ReviewBoard`. `RequirePermission items:read`; upload controls disabled with "needs items:work" when the user lacks it. |
| `app/(shell)/review/loading.tsx`, `app/(shell)/review/error.tsx` | new | Board skeleton; error boundary with generic message + Retry (TEST-19/20). |
| `app/api/review/uploads/route.ts` | new | Thin streaming proxy: `POST` only; `415` unless `multipart/form-data`; `413` on `Content-Length` over the limit sent by the page; forwards `request.body` with the original `Content-Type` (boundary) and the session bearer through `apiUpload`; passes `stage_only` through; returns upstream JSON and status untouched. `export const dynamic = "force-dynamic"` like the parts route. |
| `lib/api/file.ts` | change | `apiUpload(path, body: ReadableStream<Uint8Array>, contentType, query?, init?)` — the raw-body POST twin of `apiFile` (same base URL, token, request id, `duplex: "half"`). |
| `lib/api/openapi.json`, `lib/api/schema.d.ts` | regenerated | `npm run api:sync` after the router lands. |

### infra/

| File | Change | Purpose |
|---|---|---|
| `infra/modules/object_storage/main.tf` | change | Object lifecycle rule deleting `staging/` objects after 1 day (no scheduler in the app; the bucket expires abandoned chat stagings). |

### docs/

| File | Change | Purpose |
|---|---|---|
| `docs/sprints/bmn-ui-techy-redesign/failed-receipt-review/validation.md` | new (coder) | The §3.4 board checklist ticked item by item (lesson L-admin-act-for-absent-owner-1). |

## 3 Test plan

Written and run only in step 5. API tests under `api/tests/review/`, web unit under `web/tests/review/` and `web/tests/common/`, E2E under `web/e2e/review.spec.ts` (TEST-2, TEST-12, TEST-14). Fixtures (tiny PNG/JPEG with EXIF GPS, WEBP with EXIF chunk, clean PDF, encrypted PDF, PDF with `/JavaScript`, JPEG-with-appended-ZIP, PNG declaring 30000x30000) are generated in `api/tests/review/conftest.py` at test time, never committed binaries.

### AC1 config keys [unit]
- `api/tests/review/test_config_keys.py::test_upload_keys_registered_with_defaults` — all 8 keys exist in `CONFIG_KEYS`, group `uploads`, defaults 5_242_880 / 10 / 20 / [png,jpeg,webp,pdf] / 40_000_000 / 20 / 3600 / "high".
- `...::test_upload_key_bounds_rejected` — out-of-range ints, `True` for an int key, empty or unknown `allowed_types`, effort "extreme" raise `ConfigValidationError`.
- `...::test_falsy_but_valid_daily_quota_zero_kept` — `uploads.daily_per_user = 0` validates and is not defaulted.

### AC2 UploadService.submit [unit]
- `api/tests/review/test_sanitize.py::test_sniff_ignores_declared_type` — PNG bytes declared `application/pdf` sniff as png; text declared `image/png` sniffs None.
- `...::test_pdf_magic_only_at_offset_zero` — `%PDF-` at offset 10 is None.
- `...::test_jpeg_exif_and_gps_stripped_losslessly` — APP1 gone, pixel data (SOS..EOI) byte-identical, Pillow reports no exif.
- `...::test_png_text_and_exif_chunks_stripped` / `...::test_webp_exif_chunk_stripped_and_riff_size_fixed`.
- `...::test_trailing_bytes_after_image_end_removed` — appended ZIP removed.
- `...::test_pixel_limit_checked_from_header_without_decode` — 30000x30000 header refused; `Image.Image.load` is never called (patched to fail).
- `...::test_encrypted_pdf_refused`, `...::test_pdf_with_javascript_refused`, `...::test_pdf_with_data_before_header_refused`, `...::test_pdf_over_page_limit_refused`.
- `api/tests/review/test_upload_service.py::test_streamed_size_cap_stops_reading` — a `ByteSource` fake that counts bytes served: a 50 MB stream is cut at cap+1 bytes and returns TOO_LARGE.
- `...::test_stores_and_ingests_manual_with_uploader` — STORED, item_id set, `source_kind MANUAL`, `source_ref "upload:<subject>"`, received history row has `actor_kind USER`, the uploader's id/name and reasoning `RECEIVED_FOR_REVIEW`, object stored is the stripped bytes.
- `...::test_duplicate_sha_returns_existing_item` — second submit → `{status: DUPLICATE, item_id: first}`, no new item.
- `...::test_one_bad_file_does_not_fail_others` — [ok png, 6 MB png, text file, ok pdf] → STORED, TOO_LARGE, NOT_ALLOWED, STORED; message per file.
- `...::test_files_over_request_limit_not_allowed` — 11th file NOT_ALLOWED, first 10 processed.
- `...::test_type_not_in_allowlist_not_allowed` — `allowed_types=[png]` refuses a valid pdf.
- `...::test_unexpected_error_in_one_file_is_isolated` — ingest raising for file 2 yields NOT_ALLOWED "could not be stored" for it only; no exception escapes.
- `api/tests/review/test_ingest_actor.py::test_ingest_without_actor_unchanged` — regression on the shared intake path: history row identical to before (SYSTEM actor, reasoning "received").

### AC3 quota [unit]
- `api/tests/review/test_upload_service.py::test_quota_counted_from_history` — 19 prior received-for-review rows today for the user + 2 files → STORED then QUOTA; `quota()` = `{used: 20, limit: 20}`.
- `...::test_quota_ignores_other_users_and_yesterday` — rows of another subject and of yesterday (UTC) don't count.
- `...::test_duplicates_do_not_consume_quota`.

### AC4 effort [unit]
- `api/tests/review/test_effort.py::test_effort_for_manual_uses_review_effort` / `::test_effort_for_mailbox_uses_role_effort` / `::test_fix_hint_effort_wins`.
- `api/tests/review/test_runner_effort.py::test_manual_item_reader_calls_carry_high_effort` — ExtractRunner + AdjudicateRunner with a recording fake `LlmClient`: reader A and adjudicator requests have `effort="high"` for a MANUAL item; reader B `None`.
- `...::test_mailbox_item_reader_calls_carry_normal_effort` — same runners, MAILBOX item: reader A = `models.reader_a.effort`, adjudicator = `models.adjudicator.effort`.

### AC5 router [api]
- `api/tests/review/test_review_router.py::test_post_uploads_multipart_returns_results_and_quota` — `UploadResultOut` shape, 200.
- `...::test_post_uploads_requires_items_work` — viewer 403, no token 401.
- `...::test_post_uploads_not_multipart_415` / `...::test_post_uploads_content_length_over_limit_413`.
- `...::test_queue_lists_manual_items_only` — MAILBOX and ARCHIVED envelopes absent; row has item_id, filename, stage, status, age, confidence; paging offset/limit (limit ≤ 100).
- `...::test_queue_open_only_total`.
- `...::test_quota_endpoint`.
- `...::test_result_fields_sources_applied_and_preview` — adjudication with BOTH-equal, disagreement and B-only fields maps to A_EQ_B / A_B_DIFFERED / B_ONLY; `applied.residual` MoneyStr; `preview` page and region.
- `...::test_result_null_applied_before_apply` / `...::test_result_404_for_non_manual_item`.
- `api/tests/review/test_openapi_review.py::test_openapi_has_review_paths` — the four paths and `stage_only` query in the generated schema; web `lib/api/openapi.json` regenerated (checked by `npm run api:sync` diff in the tester's build step).

### AC6 chat tools [unit]
- `api/tests/review/test_review_tools.py::test_review_tools_registered` — `review.submit` (REVIEW, mutating, confirm_required, ITEMS_WORK, preview set) and `review.queue` (read, ITEMS_READ) are in `TOOLS` and discovered by the registry.
- `...::test_stage_only_returns_upload_ids_without_ingesting` — router with `stage_only=true`: ids returned, no work item, no quota used.
- `...::test_submit_tool_ingests_staged_uploads_via_upload_service` — executes through the registry confirm path; same history rows as the router path.
- `...::test_submit_tool_refuses_other_users_and_expired_stagings`.
- `...::test_submit_tool_hidden_from_viewer` — not in `for_principal(viewer)`.

### AC7 DropZone + proxy [unit]
- `web/tests/common/drop-zone.test.tsx::renders_title_hint_and_choose_files`, `::calls_onFiles_with_dropped_files`, `::rejects_over_maxBytes_and_over_maxFiles_client_side`, `::disabled_blocks_drop_and_picker`, `::keyboard_opens_picker`.
- `web/tests/review/uploads-route.test.ts::forwards_body_stream_with_boundary_and_bearer` (TEST-9, `apiUpload` mocked), `::rejects_non_multipart_415`, `::passes_stage_only_query`, `::maps_upstream_error_to_envelope`.
- `web/tests/review/no-second-dropzone.test.ts::only_common_drop_zone_handles_file_drops` — static scan: no other component under `web/components` sets `onDrop` with `dataTransfer.files`.

### AC8–10 Review board [browser] (`web/e2e/review.spec.ts`, against the API mock used by the e2e harness, Review board)
- `review board shows top bar, quota and upload panel copy` — "Review", env pill, Sample data, "Today 7 / 20 uploads", "Drop failed receipt images", hint line exact, "Choose files".
- `uploading files shows thumbnails with progress and status pills` — Stored, Uploading N%, Duplicate of WI-…, Over 5 MB, Not an image; Clear empties the row; "Submit 2 for in-depth review" counts eligible files.
- `review queue lists items with stage and status` — headers Item/File/Stage/Status/Age, "same stations · high effort".
- `selecting an item shows the result panel` — preview with highlighted region and "page 1 · amount", field table pills `A = B` / `A, B differed` / `B only`, adjudication note, "Applied to RCPT-… · 2 lines · residual 0.00", Open item and History links, header pill "Applied · 0.94".
- `result panel updates live as the item moves` — mock SSE event for the selected item → pill changes without reload.
- `empty queue state`, `loading result state` ("Both readers done, adjudicating…"), `upload error keeps other files` ("scan_big.png is over 5 MB. The other files were kept.").
- `review page error boundary shows retry` (TEST-17).
- `review at 375px has no horizontal scroll`.

### AC11 nav count [unit]
- `web/tests/review/nav-count.test.ts::returns_open_total_from_review_queue`, `::returns_null_on_api_error`.
- `web/tests/review/format.test.ts::source_pill_tones`, `::upload_pill_labels`.

Count: 71 named tests (API 47, web unit 14, E2E 10; each name joined by `/` counts separately).

### 3.4 Review board checklist (coder ticks each in validation.md)
- [ ] Top bar: title "Review"; env pill (warn, mono); "Sample data" muted pill (only when `/me.sample_data`); "Today N / M uploads" mono.
- [ ] Upload panel = `GlassPanel` + `PanelHeader`; `DropZone` dashed border `--line2`, drag-over `--acc-hi` border + `--acc-soft` fill.
- [ ] Copy: "Drop failed receipt images"; "PNG, JPG, WEBP or PDF · up to 5 MB each · 10 files at a time · location data is stripped" (numbers from `/review/quota`'s config values or the page's config read, not constants); button "Choose files".
- [ ] Thumbnail: preview, name, mono size, 4px `Meter` (accent while uploading), pill tones Stored ok / Uploading N% accent / Duplicate of WI-… locked / Over 5 MB err / Not an image err.
- [ ] Actions: "Clear" (outline), primary "Submit N for in-depth review" with glow; disabled with "needs items:work" for viewers.
- [ ] Review queue: `DataTable` mono uppercase headers Item / File / Stage / Status / Age; header label "same stations · high effort"; Stage mono; Status via `status-badge`; selected row tint.
- [ ] Result panel: title "In-depth review result"; header pill "<status> · <confidence>"; preview through `common/artifact-viewer` with highlight and caption "page N · amount"; field table Field / Value / Source; pills `A = B` ok, `A, B differed` warn, `B only` muted (`A only` muted); adjudication note in `--soft`; applied line "Applied to <receipt> · N lines · residual X"; links "Open item" (`/items/[id]`) and "History" (`/items/[id]#history`).
- [ ] States via `StateCard`: Empty · queue "Nothing under review" / "Drop images above. Each one becomes a work item that runs the same stations at high effort."; Loading · result "Both readers done, adjudicating…" with `SkeletonRows`; Error · upload "<file> is over 5 MB" / "The other files were kept. Crop or compress it and add it again." + "Remove file".
- [ ] Two-up columns `auto-fit minmax(400px,1fr)`, single column on narrow; no horizontal page scroll at 375px.
- [ ] Shared components used, none redefined: `GlassPanel`, `PanelHeader`, `PanelBody`, `Pill`, `MonoLabel`, `Meter`, `DataTable`, `StateCard`, `SkeletonRows`, `TopBar`, `status-badge`, `artifact-viewer`, `Button`.

## 4 Data

- No new table, **no Alembic migration** (split.md's migration list does not include this story). Quota is counted from `WORK_ITEM_HISTORY`; filenames live in the received row's payload; staged chat uploads live in Object Storage (`staging/<id>` + `staging/<id>.json`).
- Config keys have registry defaults, so nothing needs seeding; db-stored-settings' seed migration is not touched.
- Models used read-only: `WorkItem`, `WorkItemHistory`, `Adjudication`, `ExtractionReading`, applications/reservation models.
- Index note for the reviewer: the quota query filters `WORK_ITEM_HISTORY` on `ACTOR_ID`, `REASONING`, `AT`. If an index on `(ACTOR_ID, AT)` doesn't exist it's a follow-up for the merger to add to a migration story; at 20 uploads/user/day this is not a blocker.

## 5 Config and env

- DB keys (owned here): `uploads.max_file_bytes`, `uploads.max_files_per_request`, `uploads.daily_per_user`, `uploads.allowed_types`, `uploads.max_pixels`, `uploads.max_pdf_pages`, `uploads.stage_ttl_seconds`, `review.effort`.
- Read (not owned): `models.reader_a`, `models.adjudicator` (effort fallback).
- No new env variable, in api/ or web/ (scope item 3).

## 6 Risks and gates

- Decompression bombs: header-only dimension check before decode, `MAX_IMAGE_PIXELS` from config, warning escalated to error; PDFs never rendered here.
- Polyglot/encrypted/active PDFs refused; images lose trailing bytes and metadata; the stored bytes are the sanitized ones, so the dedupe hash is of the sanitized bytes (same input → same bytes, the strip is deterministic).
- Prompt injection inside receipts: reader prompts say artifact text is data; MANUAL items flow through the same validate and confidence gates as everything else.
- Request size: Starlette spools parts to disk, so the router's `Content-Length` 413 bounds total work and the service's chunked read bounds each file. A chunked upload without `Content-Length` is refused 411.
- Quota race: two concurrent requests from one user can each pass the check; worst case overshoot is `max_files_per_request - 1`. Accepted, recorded.
- `ingest()` signature change touches the shared intake path; the default keeps old behaviour and a regression test pins it.
- Next proxy: streaming `request.body` needs `duplex: "half"`; read `web/node_modules/next/dist/docs` route-handler pages before coding (research.md primary-docs).
- Coder gates (lint + type-check only, no tests): api `cd api && uv run ruff check . && uv run ruff format --check . && uv run pyright`; web `cd web && npx eslint . && npx next typegen && npx tsc --noEmit`; plus `npm run api:sync` after the router.

Next.js rule ids applied: TS-1, TS-5, TS-10, TS-13, TS-15, TS-16, TS-19, TS-20, TS-23, TS-28, TS-30, TS-31, TS-32, TS-34; API-1, API-2, API-4, API-6, API-8, API-9, API-10, API-11, API-12, API-13, API-20, API-29, API-38; SEC-5, SEC-15, SEC-16, SEC-18, SEC-30, SEC-37; SSE-24, SSE-25, SSE-26 (through `useEventStream`); TEST-1, TEST-2, TEST-9, TEST-12, TEST-14, TEST-15, TEST-17, TEST-19, TEST-20, TEST-25.

## 7 Interfaces provided (pinned)

### Consumer: assistant-chat-redesign (plannable: true)

```tsx
// web/components/common/drop-zone.tsx
export type RejectedFile = { readonly file: File; readonly reason: "too_large" | "not_allowed" | "too_many" };
export type DropZoneProps = {
  accept: readonly string[];          // MIME types, e.g. ["image/png","image/jpeg","image/webp","application/pdf"]
  maxBytes: number;
  maxFiles: number;
  onFiles: (files: readonly File[], rejected: readonly RejectedFile[]) => void;
  disabled?: boolean;
  title?: string;                     // default "Drop failed receipt images"
  hint?: string;
  variant?: "panel" | "inline";       // "inline" = compact target for the composer "+"
};
export function DropZone(props: DropZoneProps): React.JSX.Element;
```

```
POST /review/uploads?stage_only=true      (multipart/form-data, field name "files", ITEMS_WORK)
  web proxy: POST /api/review/uploads?stage_only=true (same body)
-> 200 StagedUploadsOut {
     upload_ids: string[],                 // 32 hex chars each, one per staged file, in input order of the STORED files
     files: UploadFileResultOut[],         // per-file status; STORED means staged
     quota: QuotaOut                       // not consumed by staging
   }
POST /review/uploads                      (no stage_only) -> 200 UploadResultOut { files: UploadFileResultOut[], quota: QuotaOut }
UploadFileResultOut { filename: string, status: "STORED"|"DUPLICATE"|"TOO_LARGE"|"NOT_ALLOWED"|"QUOTA", item_id: int | null, message: string }
QuotaOut { used: int, limit: int }
Errors: single ApiError shape; 401, 403, 411, 413, 415, 422.
```

Chat tool (via chat-agent-tool-registry): `review.submit {upload_ids: list[str] (1..uploads.max_files_per_request)}` → output `UploadResultOut`, result card `table_card` (File, Status, Item); `review.queue {offset: int = 0, limit: int = 20 (≤100), open_only: bool = true}` → `ReviewQueuePage`. Stagings expire after `uploads.stage_ttl_seconds`.

### Consumer: glass-theme-shell nav (not a dep listing; wiring only)

`reviewOpenCount(): Promise<number | null>` in `web/components/review/nav-count.ts`, attached to the Review entry through glass-theme-shell's count-source field. plannable: true (the field name is glass-theme-shell's; this story adapts to it).

### Other read contracts (for any later consumer)

```
GET /review/queue?offset=0&limit=20&open_only=false   (ITEMS_READ)
-> ReviewQueuePage { items: ReviewQueueRowOut[], total: int, offset: int, limit: int }
ReviewQueueRowOut { item_id: int, filename: string | null, stage: Stage, status: ItemState, payment_status: PaymentStatus | null,
                    age_seconds: int, created_at: datetime, confidence: float | null }
GET /review/quota -> QuotaOut
GET /review/items/{item_id}/result -> ReviewResultOut {
  item_id: int, status: ItemState, payment_status: PaymentStatus | null,
  fields: [{ field: string, value: string | null, source: "A_EQ_B"|"A_B_DIFFERED"|"A_ONLY"|"B_ONLY" }],
  adjudication_note: string | null, confidence: float | null,
  applied: { receipt_number: string, lines: int, residual: MoneyStr, currency: string } | null,
  preview: { artifact_key: string, part_no: int, page: int, region: { x: float, y: float, w: float, h: float } | null } | null
}   (404 when unknown or not MANUAL; adjudication fields empty and confidence null while readers run)
```

`effort_for(item: WorkItem, role: ModelRole, config: ConfigSnapshot) -> str | None` in `cashapp/services/review/effort.py` is the only effort lookup for readers and adjudicator.

## 8 Assumptions

- Upload permission is ITEMS_WORK; queue, quota and result are ITEMS_READ (story assumption kept).
- Filenames are stored in the received history row's payload, not a new column (no migration).
- Quota day is the UTC calendar day; only STORED uploads count; duplicates and refusals don't.
- Pixel-limit and page-limit breaches return TOO_LARGE; encrypted/polyglot/active PDFs, unknown magic, a type outside the allowlist and files beyond the per-request limit return NOT_ALLOWED.
- The result endpoint adds `item_id`, `status`, `payment_status`, `applied.currency` and `preview.part_no` to the story's shape (additive; the artifact viewer needs the part number).
- The board refetches on the existing flow SSE events instead of a new review stream (no new stream, nothing emitted to the bus).
- Images are sanitized losslessly (segment/chunk removal), not re-encoded, so the read quality is unchanged.
- Abandoned stagings are removed by a 1-day Object Storage lifecycle rule (no in-app sweeper: no scheduler, no third poller).
- research.md tied the quota to the llm_usage budget; this plan uses the plain count the story pins.
