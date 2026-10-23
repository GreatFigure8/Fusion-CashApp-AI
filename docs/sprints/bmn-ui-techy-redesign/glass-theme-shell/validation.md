# validation: glass-theme-shell (coder checklist)

Coded against the plan's Shell board checklist; nothing was run in a browser (coder gates are lint and type-check only).

- [x] Ground, rail and main widths (AppShell: `bg-blueprint`, p-4, rail `flex-[1_1_200px]`, main `flex-[999_1_560px]` `min-w-0`, gap 16)
- [x] Rail brand tile with glow, "CashApp", mono "AI"
- [x] Nav item chip/label/count, min-height 40, radius 10, hover `#ffffff0a`-like tint
- [x] Active item ring and glow, `aria-current="page"`
- [x] Codes and order DB FL EX EN RV RP LB CF
- [x] User row (28px initials avatar, 13px name, 10px mono role) with hairline above
- [x] TopBar (title, crumb, env pill, Live pill, Sample data pill, right slot, search `⌘K`, min-width 260)
- [x] Footer (Bus healthy/unhealthy, lag, dlq warn, pollers, region, "Bus status unavailable")
- [x] Glass, pills, buttons (warn, warn-solid, glow), type tokens
- [x] Loading, denied and API-down states with the specified copy
- [x] Mobile bar + sheet below 1024, 4px focus halo, reduced-motion handling

Deviations: `components/shell/nav-counts.tsx` (not `.ts`, it renders JSX); `DataTable` column meta typed through the `columnMeta` feature slot instead of module augmentation; `tests/support/fixtures/dto.ts` gained the three new `/me` fields so `tsc` stays green.
