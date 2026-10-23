# failed-receipt-review: Review board checklist (coder)

Ticked = implemented in code. Nothing was run in a browser (coder gates are lint and type-check only).
`[~]` = coded against a pinned dependency contract; renders correctly only after glass-theme-shell merges.

- [x] Top bar: title "Review" (`TopBar`); env pill and Sample data come from the shell's `TopBar`; "Today N / M uploads" mono in `pills`.
- [~] Upload panel = `GlassPanel` + `PanelBody`; `DropZone` dashed `border-line-strong`, drag-over `border-primary` + `bg-brand-soft`.
- [x] Copy: "Drop failed receipt images"; hint built by `uploadHint()` from `GET /review/limits` (numbers are configuration, not constants); button "Choose files".
- [~] Thumbnail: preview, name, mono size, `Meter` (accent while uploading), pills Stored ok / Uploading N% accent / Duplicate of WI-… locked / Over N MB err / Not an image err. `Meter` size 5 is the nearest pinned size to the 4px board bar.
- [x] Actions: "Clear" (outline), primary "Submit N for in-depth review" with glow; disabled for viewers with the line "Uploading needs items:work."
- [~] Review queue: `DataTable` Item / File / Stage (mono) / Status (`StatusBadge`) / Age; header label "same stations · high effort"; selected row via `selectedRowId`.
- [~] Result panel: "In-depth review result"; header pill "<status> · <confidence>"; preview through `common/artifact-viewer` with the amount highlight and caption "page N · amount"; Field / Value / Source table with pills `A = B` ok, `A, B differed` warn, `A only` / `B only` muted; adjudication note in warn ink; applied line; links "Open item" and "History".
- [~] States via `StateCard`: empty queue "Nothing under review"; loading result "Both readers done, adjudicating…" with `SkeletonRows`; error upload "<file> is over N MB" / "Crop or compress it and add it again." with "Remove file".
- [x] Two-up columns `auto-fit minmax(min(100%,400px),1fr)`; single column when narrow.
- [~] Shared components used, none redefined: GlassPanel, PanelHeader, PanelBody, Pill, MonoLabel, Meter, DataTable, StateCard, SkeletonRows, TopBar, StatusBadge, ArtifactViewer, Button/ActionButton.

Deviations recorded: the board refetches through the shell's existing `useFlowStream().subscribeItemChanged` (one connection per tab) instead of opening a second `useEventStream`; `GET /review/limits` was added so the hint and limits are not constants; `ReviewResultOut.preview` also carries `kind` and `media_type` for the artifact viewer.
