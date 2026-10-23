# Story (GitHub issue #48, verbatim from Jonathan)

The UI for the cash app is lacking and kind of plain. It needs a techy feel to it. What this UI needs to do is show the user progress and manage exceptions to the process. It primarily needs to report on progress: receipts matched, money made, model efficiency. The matching algorithm is everything in this app, so we need ways to refine it. I like refining it through chat, so we need an assistant UI chat that looks like the aix-payroll-compare chat (local checkout: D:\AIX-Payroll-Compare). We need the capability in the UI to submit receipt images that failed for in-depth review, and other things, but this is enough for a start on a UI.

Issue: https://github.com/GreatFigure8/Fusion-CashApp-AI/issues/48

Acceptance criteria (from the issue):
- Redesigned dark, techy visual theme applied through shared components, no per-page duplicates.
- Progress dashboard: receipts matched, money applied (by currency), model efficiency (per-model accuracy, cost, adjudicator agreement, auto-fix rate) (inferred).
- Exception workbench restyled to match; exceptions only, applied items hidden by default (inferred).
- One shared assistant chat component styled like the aix-payroll-compare chat, configured by props (context, system prompt key, actions), usable for refining matching rules.
- Upload one or more failed receipt images and submit for in-depth review; appears as a work item with artifact stored and a review result visible in the UI.

Repo rules: see CLAUDE.md (python API owns data/logic; web/ is a thin Next.js client; shared components once; Haiku is the chat workhorse; zero data retention).
Local rule: `dev` is protected in this repo. Never push dev. Land work on dev by pull request (`gh pr create --base dev`, merged with `gh pr merge --merge`).
