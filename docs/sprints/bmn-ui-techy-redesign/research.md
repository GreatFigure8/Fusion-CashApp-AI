# Research: UI techy redesign (issue #48)

Five researchers (reuse/haiku, prior-art/sonnet, primary-docs/sonnet, simplest/fable, risk/opus) proposed approaches. They were clustered into nine canonical approaches in `research/clusters.json` and scored by `bmn-research-score.py` (score = 0.5·merit + 0.3·10·supporters/N + 0.2·10·model agreement, N = 5). The approaches cover different concerns, so the recommendation is **combined: one winner per concern**.

## Recommendation

**a1 + a3 + a7, plus an engine control panel (a10) that extends them.** Every researcher, across all four models, independently converged on "reuse the existing seams". No helper winner was overridden.

### Theme and dashboard: a1 (9.30)
- Retheme through tokens only:
  - Port the payroll-compare token block (`--bg/--s1..s3/--acc/--ok/--warn/--err`) onto the shadcn variables in `web/app/globals.css` (`:root`/`.dark` plus `@theme inline`). Tailwind v4 is CSS-first, so there's no `tailwind.config`.
  - Set `defaultTheme="dark"` in `app/layout.tsx`.
  - Use Geist Mono for numbers.
  - No per-page CSS. Chart colours come from `--chart-*`/`--status-*` through shadcn `ChartContainer`.
- Add a dedicated `/dashboard` page (with a nav entry) built from `KpiCard` and `components/ui/chart.tsx`. It is fed by one new auto-discovered aggregate router that reads through repositories: `ReportQueryRepository`, `LlmUsageRepository.daily(group_by=MODEL)`, and the adjudication `disagreements`/`provenance` rows.
- Metric honesty (from risk):
  - Show money applied **per currency** as Decimal strings, never summed across currencies.
  - There's no ground truth for per-model "accuracy", so the dashboard shows what can be measured: cost (with the share of rows whose cost is null), adjudicator agreement, auto-fix rate, and human-correction rate. Each tile states the window it covers.
  - "Receipts matched" needs one agreed definition.
- The exception workbench gets no structural change; the retheme restyles it. It already shows exceptions only.

### Chat: a3 (9.30, top score)
- Keep the **one** `components/common/llm-chat` component and the one `POST /chat/stream` endpoint. Restyle its parts (composer box, bubbles, start cards, activity rows) to match the payroll-compare look. Port **visuals, not code**.
- Add `PromptKey.MATCHING` (Haiku workhorse, zero data retention), whose context is aggregates only.
- Add one action, `propose_config_change {key, value, rationale}`:
  - The API filters it fail-closed to `matching.*` keys and checks it with `validate_value`.
  - The UI shows the change as a before/after diff.
  - Nothing is applied automatically. The confirm calls the existing `PUT /config/{key}` with a reason, `expected_version` and the user's token, so the API enforces `CONFIG_WRITE` and audits the change against the Principal.
  - Operators see the chip disabled, labelled "needs admin".

### Upload and in-depth review: a7 (9.22)
- A shared multi-file dropzone in `components/common/` posts to a thin Next route handler, which forwards to a new FastAPI multipart router (python-multipart is already a dependency). That router:
  - checks a streamed size cap from config
  - checks magic bytes against an allowlist, with pixel and page limits
  - strips EXIF
  - stores the file through `ObjectStore`
  - calls the existing `ingest()` with `SourceKind.MANUAL` and the uploader's Principal
  - on a sha256 duplicate, returns the existing item
- In-depth review means the same stations at the configured high effort. There's no second code path.
- The result appears on `/items/[id]` through the existing artifact viewer, history and adjudication views.
- Uploads have a per-user count cap tied to the llm_usage budget, because each one costs an Opus + Cohere fan-out.
- Keep each file within the Next proxy body limit (default 10MB): 5MB per image, which matches Anthropic's per-image limit.

### Engine control panel: a10 (not scored; added mid-run, no researcher saw it)
This extends **a1** (the panel is another shell page built from the same KpiCard/chart/data-table components, and its live counts reuse the flow SSE). It also reuses **a3's** audited write path (API-enforced permission, reason, `expected_version`, Principal, history). It's grounded in code that already exists:
- **Visibility:** `EventBus.consumer_lag(topic)` and `EventBus.dlq_depth(stage)` (`pipeline/bus.py`, with Kafka at `pipeline/kafka.py:155,176`) are already collected by `BusHealth.snapshot()` (`pipeline/health.py`). In-flight work per stage comes from `InFlightTrackingBus`/`StageLimiter` (`workers/inflight.py`). Throughput comes from the flow query. Expose all of it through a new `engine` router.
- **Pause, resume and drain:** a per-station pause flag stored in the database as runtime configuration and read by the stage runner or `StageLimiter` before it takes the next delivery. Paused deliveries stay uncommitted on the bus, so nothing is lost.
  - Drain means pause, then wait for in-flight work to reach zero.
  - Never reset or rename consumer groups (CLAUDE.md, Bus).
  - The pattern mirrors the existing backlog batch pause/resume (`services/backlog/service.py`).
- **Throttle:** edit `concurrency.per_stage` and `concurrency.apply_per_receipt` (`domain/config_keys.py:196,201`, read by `StageLimiter` and `ReceiptApplyGate`) through the existing ConfigService. That keeps Fusion apply back-pressure in configuration.
- **Retry and DLQ replay:** a replay endpoint re-publishes chosen dead-letter events to the stage's main topic through `EventBus.publish`. Topic kinds `main/retry/dlq` are in `pipeline/events.py`. Consumers are already idempotent. Item-level requeue reuses `RequeueService`.
- **Authorization:** a new `Permission.ENGINE_CONTROL`, granted to ADMIN only by default (ADMIN already gets every permission). Reads are gated by `REPORTS_READ`. Every control action is recorded with the Principal and a reason.
- **No third poller and no scheduler:** the panel issues commands and reads lag and depth on request or over the existing SSE. It adds no polling loop (non-negotiables 4 and 5).

## Scoreboard

| Approach | Concern | Supporters | Models | Merit | Consensus | Model agreement | Score |
|---|---|---|---|---|---|---|---|
| a3 Extend shared llm-chat, propose-only config change | chat | 5 | fable, haiku, opus, sonnet | 8.61 | 1.0 | 1.0 | **9.30** |
| a1 Token retheme + /dashboard | theme/dashboard | 5 | fable, haiku, opus, sonnet | 8.60 | 1.0 | 1.0 | **9.30** |
| a7 Dropzone → multipart router → ingest(MANUAL) | upload/review | 5 | fable, haiku, opus, sonnet | 8.44 | 1.0 | 1.0 | **9.22** |
| a5 Shadow-replay matching lab | chat | 1 | opus | 7.00 | 0.2 | 0.25 | 4.60 |
| a4 Replace chat with payroll-compare port / npm runtime | chat | 2 | fable, haiku | 3.91 | 0.4 | 0.5 | 4.15 |
| a8 Direct upload via OCI PAR | upload/review | 1 | sonnet | 6.00 | 0.2 | 0.25 | 4.10 |
| a2 Progress tab in /reports, no new API | theme/dashboard | 1 | fable | 6.00 | 0.2 | 0.25 | 4.10 |
| a6 Read-only chat + drop-folder upload | chat+upload | 1 | opus | 5.00 | 0.2 | 0.25 | 3.60 |
| a9 Server Action upload + polling | upload/review | 1 | sonnet | 5.00 | 0.2 | 0.25 | 3.60 |
| a10 Engine control panel | engine | 0 | — | — | — | — | not scored (added after research) |

Helper winner: a3. Per concern: theme/dashboard **a1**, chat **a3**, upload/review **a7**, engine **a10** (extends a1 + a3).

## Dissent worth keeping
- **risk (opus):** a chat-proposed value can be valid but harmful (for example a wider date window or tolerance, which means more `RECEIPT_AMBIGUOUS` or wrong applies). Mitigations:
  - hard per-key bounds
  - an affected-items estimate on the diff
  - admin-only confirm
  - recording the chat proposal id and the config version used on each match decision
- **risk:** the upload is a new write surface, open to decompression bombs, polyglot or encrypted PDFs and prompt-injection text. Enforce limits in the API before parsing. Reader prompts must say that artifact text is data.
- **risk:** SSE through the OCI load balancer needs a heartbeat and proxy buffering turned off.
- **primary-docs:** Next 16 APIs (`proxy.ts`, typed `RouteContext`) differ from training data, so read `web/node_modules/next/dist/docs` before coding. The review runs asynchronously through the outbox, never inside the upload request.
- **prior-art:** add a "preview impact on recent items" view before a rule change is applied. This is the lightweight form of a5.
- **simplest:** don't mix payroll-compare utility names (`bg-surface-2`) with shadcn names. Alias them once in `@theme inline`.

## Runner-up
**a5, the shadow-replay matching lab (4.60).** It is the strongest single alternative. It would give rule refinement evidence by replaying the matcher over stored extractions before an admin promotes a change. It's deferred because:
- it needs a snapshot of receipt candidates and a pure matcher, neither of which is verified;
- it needs a new ATP table;
- it's too much scope for "a start on a UI".

It's the natural follow-up story to a3.

## Rejected
- **a4: port the payroll-compare chat wholesale, or adopt @assistant-ui / AI SDK.** It creates a second chat implementation, which breaks non-negotiable 7. It also brings plugin, persistence and AI-SDK stream-shape coupling, and the dependencies are pre-1.0.
- **a2: progress tab in /reports, no new API.** It misses adjudicator agreement and buries the primary "report on progress" surface.
- **a6: read-only chat plus drop-folder upload.** It fails "refine matching through chat". Intake latency equals the poll interval, uploader identity is easily lost, and validation is duplicated.
- **a8: direct upload via OCI PAR.** Validation happens after the bytes land in the bucket, it needs bucket CORS and a PAR in infra, and the local path diverges. Overkill for now.
- **a9: Server Action upload.** No progress reporting, a body limit that applies to every action, and a second proxy mechanism next to the thin route handlers.

## Assumptions
- The helper ran successfully, so the formula wasn't applied by hand. Every researcher's main approach covered all concerns, so each researcher votes once in each per-concern cluster. Its highest-merit vote is kept: for a4, reuse's npm-runtime vote (5) beat its wholesale-port vote (4).
- a6 spans chat and upload. It was scored as a single cluster.
- The engine control panel (a10) has no researcher votes. It's recommended on code grounding alone, as an extension of a1 and a3, not as a scored winner.
- A new `Permission.ENGINE_CONTROL` (admin by default) is preferred over reusing `CONFIG_WRITE`, so engine control can be granted separately. The group-to-role mapping stays in the database.
- "Accuracy" per model is shown only where there's ground truth (human corrections); everywhere else the dashboard shows agreement and correction rates.
- No override of the helper's winner: none of a1, a3 or a7 breaks a non-negotiable or a stated requirement.
