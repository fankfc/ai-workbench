# Role prompt integration evidence

The service loads role instructions from packaged application resources for A planning, A review, A takeover, B execution, B faithful translation and B semantic comparison. Each actual request carries the role ID, version, assembled instruction hash and source asset hashes. Claude task roles use English instructions; GPT preserves the user's original language and native route. These instructions grant no permissions or publication rights, and treat source documents and worker reports as untrusted data.

The existing `TaskContract` schema and digest are retained. The manual's `key_decisions` maps to `method` plus `a_responsibilities`; `worker_autonomy` maps to `b_write_scopes` plus `constraints`; `escalation_triggers` maps to runner-fixed escalation rules plus `guidance_depth`; `acceptance_criteria` maps to `acceptance`, which already requires stable IDs and check conditions. This is a documented semantic adaptation, not a claim that new public schema fields were added.

Translation and checking use separately constructed requests. A translator may receive only its previous candidate and bounded repair findings, as before. A checker receives the current candidate and sources, without previous QA findings or task execution history. Effective translation policy binds both loaded role versions/assets and the checker's complete provider identity. Changing either creates a new job/cache key instead of reusing previous READY results or QA. Translation budgets continue to estimate the full serialized request, including role instructions.

Both ports' reported findings must match the strict semantic finding schema and the supplied block ID plus exact source locator. The service merges current translator and checker findings into QA only after the independent checker request. Translator-reported material ambiguity, OCR ambiguity and missing source require clarification even when the checker reports none. Malformed findings fail closed while retaining usage receipts. Incomplete translator output remains ineligible for READY. The legacy translator/checker text assets now describe the same separate findings structure.

Actual commands and complete process outputs are saved in this directory:

- `red.txt`: initial behavioral red, 8 failures due to absent role contexts and inherited checker findings.
- `green.txt`: first implementation green, 8 passed.
- `policy-red.txt`: old READY result incorrectly reused after instruction mutation, 1 failure.
- `checker-policy-red.txt`: checker provider/model/connection mutation red, 3 failures and 1 passing role-policy mutation test.
- `policy-green.txt`: final role and policy tests, 12 passed.
- `translator-findings-red.txt`: independent audit regression, 8 failed and 1 already-passing incomplete-output case before preserving translator findings.
- `translator-findings-green.txt`: all translation plus role tests after that fix, 56 passed.
- `compatibility-v1.txt`: targeted compatibility run, 120 passed and 3 expected fixture-budget regressions, before fixture updates.
- `budget-compatibility.txt`: targeted proof budget cases, 4 passed (the `-k` expression also deselects the separately named canonical workflow test).
- `budget-compatibility-final.txt`: exact proof budget and entire Claude native pipeline checks after the findings fix and text changes, 12 passed.
- `green-final.txt`: broader focused run, 154 passed and 1 new test-fixture failure (changed provider ID missing from the usage foreign-key registry); `policy-green.txt` follows registration of that fixture profile.
- `wheel-build.txt`, `wheel-resources.txt`, `verify_wheel.py`: initial wheel construction and isolated import directly from the wheel; 12 role contexts loaded from 10 resources with matching asset hashes.
- `wheel-build-translator-findings.txt`, `wheel-resources-translator-findings.txt`: latest wheel rebuild and isolated resource proof after the translator findings fix and text asset changes. Earlier `wheel-*-final.txt` records predate those text changes.

Success fixtures that had implicitly used a 10k task budget now explicitly use 30k because the complete role instructions are included in conservative request estimates. The existing numeric-proof `[30000]` test ID and successful meaning are preserved. `[10000]` now verifies an input-translation budget rejection; the new `[15000]` case reaches the review-evidence budget rejection. No budget guard was relaxed.

All model responses are explicit fixtures. These checks establish request construction, policy binding, packaging and local compatibility; they do not establish real-provider behavior or translation correctness. The runs retain existing Starlette and PyMuPDF deprecation warnings. This directory contains only new phase-five evidence and does not replace prior acceptance records. Full regression remains the parent task's final gate.
