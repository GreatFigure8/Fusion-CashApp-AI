# Design options (Claude Design canvas)

Project: CashApp UI techy redesign, https://claude.ai/artifact/NgfTaH1tfvxXVLaMVamDEc (private until shared from the page's Share menu).

The canvas has one row per direction. Each row has nine boards, and each board shows its empty, loading and error states (some boards also show a permission-denied state):

1. shell and theme
2. progress dashboard (live)
3. engine control (live, with the fusion-sql-mcp health row)
4. exception workbench
5. assistant agent (the main interface)
6. failed-receipt review
7. Matching Lab
8. reports and export
9. settings (DB-stored, with the fusion-sql-mcp connection card)

Every other screen also carries the assistant, docked or as a command bar. All figures are sample data.

| key | name | summary | path | open_url |
|---|---|---|---|---|
| A | Phosphor Console | Terminal ops console: monospace throughout, phosphor green on black, bracketed status tags and ASCII meters. The assistant docks at the bottom of every screen. | project/phosphor/ | https://claude.ai/artifact/NgfTaH1tfvxXVLaMVamDEc |
| B | Glass Orbit | Refined dark glass on a blueprint dot ground, Geist and Geist Mono, electric-blue and teal accents. Closest to the payroll-compare tokens. The assistant is a floating composer with chips on every screen. | project/glass/ | https://claude.ai/artifact/NgfTaH1tfvxXVLaMVamDEc |
| C | Instrument Deck | Dense Bloomberg-style terminal: amber ticker, function-key navigation, condensed IBM Plex. The assistant is the ASK/CMD command bar on every screen, and F12 opens the full chat. | project/deck/ | https://claude.ai/artifact/NgfTaH1tfvxXVLaMVamDEc |

Assumptions:
- The chat keeps the payroll-compare structure in all three directions, recoloured for each: 40px mono header, right-aligned user bubble, activity rows, rounded composer with a 32px send button, and a kbd hint row.
- "Lab" is added as a nav entry.
- The canvas could not be rendered for a visual check, because the browser pane needs a claude.ai sign-in. Instead, all 28 board files passed a static check: tag balance, props JSON, the logic class running, and every template hole resolving.
