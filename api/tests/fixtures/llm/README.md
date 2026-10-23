# Recorded LLM fixtures

Status: UNVERIFIED AGAINST LIVE. Every file here is synthetic: the remittance is invented
(`synthetic_remittance.txt`: payer "Acme Test Payer", USD 1250.00, two invoices) and the
"model output" was written by hand, not produced by a model. They exist so the replay client
(`cashapp.integrations.llm.fake.ReplayLlmClient`) and the extract station can be tested without
network access.

- `extract_synthetic_a.json`, `extract_synthetic_b.json`: one recording per reader. Each is keyed
  by `(purpose, parts_sha256)`; the digest covers the request parts that
  `build_reader_request` produces for the text part `[part 1: text]\n` + `synthetic_remittance.txt`.
  Changing the reader instruction or the part labels changes the digest, so regenerate the
  recordings whenever `PROMPT_VERSION` changes.
- `verified_against_live` stays `false` until a `-m live` probe has run against the real model and
  its output has replaced the hand-written one. For reader B (Cohere on the dedicated endpoint)
  the request shape itself is unverified: flip the flag only after
  `tests/live/test_llm_live.py::test_cohere_dedicated_endpoint_live` passes.

The synthetic artifacts used by the PDF helper and the live probes are in
`../artifacts/synthetic_remittance.pdf` (text layer) and `../artifacts/synthetic_remittance.png`.
