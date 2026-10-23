synthetic: true

# Prior-build fixtures

These files are generated from fake data so tests and the eval harness can run before the real data exists. Replace them by running the real command below, then this first line becomes `synthetic: false`.

- Format version: 1
- Origin: synthetic source, seed 43
- Key id: 48df5e0fec12
- Regenerate: `uv run python -m cashapp.tools.anonymise --synthetic --seed 43 --out tests/fixtures/prior`

Layout: `day/messages.jsonl` (one extraction plus outcome per line), `day/fusion.json` (FusionScenario shape), `labelled/failures.jsonl` (AR labels), `manifest.json`.

Never commit the HMAC key or the source folder. Keep the denylist file outside the repo and set `CASHAPP_IDENTIFIER_DENYLIST` in the shell, not in `api/.env`.
