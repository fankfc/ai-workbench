# Translation fixture budget repair

The full-regression diagnostic failures were reproduced before edits with `-x` in both `test_clarification_translation.py` and `test_output_translation.py`. Actual red process outputs are `translation-clarification-red.txt` and `translation-output-red.txt`.

`translation-budget-probe.py` runs isolated service roots with explicit fixture ports and prints actual workflow outcomes and persisted translation job failures. Its saved output, `translation-budget-probe.txt`, shows both 10k fixtures failed with `TRANSLATION_BUDGET_EXHAUSTED` before any translator or checker call. Clarification stopped at `CLAUDE_INPUT_TRANSLATION_NOT_READY`; output staging raised `OUTPUT_TRANSLATION_FAILED`. The same fixtures with a 30k allowance reached the intended clarification/output gates. No real model requests were issued.

An initial local 30k override in the two fixture setups produced `translation-green.txt`: 18 passed. This intermediate workaround was then removed in favor of the parent task's shared test factory change: `tests/support/contracts.py::make_contract` now defaults Claude success fixtures to 30k and preserves GPT's 10k default. Explicit low-budget boundary cases still override the factory value. No product budget or QA guard changed.

The output fixture previously requested the default GPT contract despite its Claude route. Its final setup passes `model_family=route['model_family']` before computing the decision digest, so it receives the correct Claude fixture budget and contract family. `review_case` uses its existing explicit Claude family and needs no remaining local override. No shared helper was edited by this repair agent; the parent owns that shared change.

Final actual verification is `translation-green-shared-helper.txt`: both complete translation integration test files plus `test_restart_finishes_staged_claude_answer_without_translation_or_english_leak`, **19 passed**, one existing Starlette deprecation warning, exit 0. The source and tests were frozen again after this change. The parent task owns the fresh full-regression rerun.
