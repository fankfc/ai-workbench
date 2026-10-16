# Artifact fixture budget diagnosis

The five Claude atomic-publication cases and the Claude document-invalidation case failed before their intended assertions: `OUTPUT_TRANSLATION_FAILED`. Their persisted output translation jobs record `TRANSLATION_BUDGET_EXHAUSTED`; see `artifacts-red.log/xml` and `artifacts-diagnosis.json`.

An observational wrapper called the unchanged product budget checker and captured the actual request estimate: 9,884 tokens; fixture total 10,000; A reserve 2,000; already known usage 96; remaining B allowance 7,904; result `allowed: false`. The GPT native-bundle control passed and made no translation calls. See `artifacts-budget-observations.json` and `artifacts-budget-diagnostic.log`.

A temporary local Claude-only 30,000 fixture allowance produced 8 passing cases (`artifacts-green.log/xml`). It was then removed after root introduced the shared success-fixture allowance in `tests/support/contracts.py`: Claude 30,000, GPT 10,000, with explicit numeric-budget tests retaining their overrides. No changes remain in the artifact helper from this diagnosis, and no product guards changed.

The final run against that central helper passed the original six cases plus two GPT controls: **8 passed, 6 existing deprecation warnings**, exit zero. Evidence: `artifacts-central-green.log/xml`.
