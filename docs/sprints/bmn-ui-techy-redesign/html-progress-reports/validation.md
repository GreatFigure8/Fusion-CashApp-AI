# validation: html-progress-reports (restyle part, coder)

Implemented against the plan's UI checklist; nothing verified in a browser (coder runs no browser).

- [x] Existing panels (aging table, failures-by-code chart, daily summary, partially paid) sit in GlassPanel/PanelHeader/PanelBody; tables use DataTable (mono uppercase headers, right-aligned mono numbers).
- [x] Empty states use StateCard (empty); load errors use StateCard (error) with Retry; reports error.tsx uses StateCard.
- [x] CSV/XLSX buttons remain outline buttons; export route and links unchanged.
- [x] Tabs use the line variant; no per-page CSS or colour literals.
- [ ] Not verified visually: builder, preview and states (built in the earlier part), responsive behaviour at 375 px, tab line variant look.
