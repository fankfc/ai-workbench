# Native assembly independent review v2

Date: 2026-10-14. Scope: `runtime/supervisor.py`, `native_executor.py`, `planning.py`, `native_validation.py`, and API `application.py`, `turns.py`, `tasks.py`. Supporting reads were limited to the prepared workflow handoff, publisher, recovery, and their synthetic tests. This reviewer changed no application or test source.

Later follow-up: the two assembly findings were subsequently assigned to this lane for repair. Their before-fix evidence remains unchanged below; the bounded repair, final GREEN, and lane freeze are recorded separately in [native backend assembly repair](C:/Users/asd15/Documents/ChatGPT/ai/docs/acceptance/part-one-closeout/native-backend-assembly-repair.md).

This is a bounded independent review, not a production or merge-readiness approval. The extra reviewer/architect lanes required by the local code-review skill could not be started because all four collaboration slots were occupied. Root's concurrent repairs require their own final verification; the observations below preserve the reviewed state.

## Fresh synthetic verification

Executed from the repository root with its existing project interpreter:

```powershell
& .\services\orchestrator\.venv\Scripts\python.exe -m pytest tests/integration/test_conversation_api.py tests/integration/test_native_supervisor.py tests/integration/test_native_planning.py tests/integration/test_prepared_workflow.py tests/integration/test_native_validation.py tests/integration/test_native_publication.py tests/integration/test_recovery.py -q
```

Observed result: **113 passed, 1 warning in 11.56s; exit code 0**. The warning was the existing Starlette TestClient/httpx deprecation. The default `not real_provider` filter remained enabled. These selected tests use in-memory fixture capture events or FakeProvider, real local SQLite/storage/leases, and FastAPI TestClient. This review performed zero external model, native CLI, authentication, or network operations.

The run exercises the API cancellation fence, domain idempotency, durable supervisor claim, old/foreign owner rejection, post-plan revalidation, planning intent and usage persistence, atomic prepared-plan ownership transfer, current-byte publication fences, and conservative unknown-remote restart behavior. Passing those tests does not prove live provider capability or a fully assembled production backend.

## Concrete findings

### HIGH — supervisor destroys staged READY resumability after a publish interruption

Evidence: [supervisor.py:168](C:/Users/asd15/Documents/ChatGPT/ai/services/orchestrator/app/runtime/supervisor.py:168) excludes terminal/BLOCKED/PAUSED states from its failure transition but not READY. [supervisor.py:226](C:/Users/asd15/Documents/ChatGPT/ai/services/orchestrator/app/runtime/supervisor.py:226) invokes this path on any publication exception. [native_executor.py:34](C:/Users/asd15/Documents/ChatGPT/ai/services/orchestrator/app/runtime/native_executor.py:34) permits result binding only in OUTPUT_PREPARING, READY, or PUBLISHED.

A standalone zero-model probe assembled the existing fixture planner, the actual Workflow with two FakeProviders, the actual NativeTaskExecutor, and TaskSupervisor. It injected a RuntimeError at `NativePublisher.publish`, after executor staging and the durable transition to READY. The corrected probe finished with exit code 0 and returned:

```json
{
  "supervisor_returned_none": true,
  "state_after_interrupt": "BLOCKED",
  "resumable_public_release_present": true,
  "resume_result": "NATIVE_RESULT_BINDING_REQUIRED",
  "public_count": 0,
  "planning_starts": 1,
  "b_starts": 1,
  "a_starts": 1,
  "real_model_operations": 0
}
```

Risk: an already reviewed and staged local answer cannot use the executor's publication replay path after this assembled dispatcher interruption. It remains safely unpublished, so the observed defect is loss of resumability, not unauthorized publication.

Concrete fix: preserve a valid staged READY state when publication is interrupted, while retaining cancellation, latest-attempt, foreign-owner, revision, evidence, and release-gate fences. Add the above full planner→Workflow→executor→supervisor regression. The existing [direct-executor READY test](C:/Users/asd15/Documents/ChatGPT/ai/tests/integration/test_prepared_workflow.py:107) bypasses `_audit_failure` and therefore does not cover this failure.

Status at review: reported to root; no repair performed by this reviewer.

### HIGH — executor-only cancellation cannot clean up the separate planning runtime

Evidence: [native_executor.py:45](C:/Users/asd15/Documents/ChatGPT/ai/services/orchestrator/app/runtime/native_executor.py:45) cancels only `workflow.adapter` and `workflow.reviewer`; [planning.py:49](C:/Users/asd15/Documents/ChatGPT/ai/services/orchestrator/app/runtime/planning.py:49) retains a separate `planner.runtime`. [supervisor.py:185](C:/Users/asd15/Documents/ChatGPT/ai/services/orchestrator/app/runtime/supervisor.py:185) delegates cancellation exclusively to the injected binding callback.

Consequently, a binding using `executor.cancel` alone omits the active A-planning runtime. Existing [supervisor planning cancellation coverage](C:/Users/asd15/Documents/ChatGPT/ai/tests/integration/test_native_supervisor.py:170) replaces the callback with a fixture callback that releases its waiting planner; it proves delegation but not cleanup of all three runtime roles.

Concrete fix: the trusted assembly callback must combine `planner.runtime.cancel` and executor cleanup of B/A workflow roles, inspect every cleanup result, and keep local cleanup distinct from confirmed remote stop. Root confirmed this boundary and is adding a private native backend composition layer. That new layer was not present in the reviewed assembly, and no claim is made here about its later tests.

Status at review: confirmed with root; implementation owned by root.

## Report and capability boundaries

- `native-supervisor-revocation-green.log` is a historical failed run despite its filename: **1 failed, 16 passed, exit code 1**, failing `test_planning_failure_emits_fixed_public_error_once`. Preserve it as before-fix evidence. The fresh 113-test run above includes the current passing test; final consolidation needs a new final artifact rather than citing that historical log as successful.
- `native-assembly-root-regression.json`, `prepared-workflow-final-green.json`, and `native-planner-model-budget-green.json` record exit code 0 for their earlier commands. They are authoring evidence with earlier timestamps and no Git commit; they do not replace the fresh scoped result or prove a final frozen source snapshot.
- `application.py` still performs conservative startup recovery with a synchronous unknown result. `TaskSupervisor.claim` dispatches new RECEIVED work and will not recreate unknown accepted work. Query/observe of a live remote request and automatic dispatch of an already staged READY release were not verified by this review.
- The fresh registry tests establish actual immutable Python parsing, rejection of broken/arbitrary-command conditions, and the stored mixed dependency check. No fresh paper/document mechanical test or live multi-domain acceptance was added.
- The public API remains fail-closed when no private backend factory is supplied. A fixture registry cannot enter a real-mode supervisor. Production provider registration, identity/scope qualification, real usage, and remote stop confirmation remain outside this evidence.

## Source snapshot observed after the probe

Hashes were read at `2026-10-14T07:10:46Z` from the shared mutable workspace. They identify the source observed at that point; they are not a claim that concurrent root-owned source remained unchanged throughout the entire test run.

| File (under `services/orchestrator/app/`) | SHA-256 |
| --- | --- |
| `runtime/supervisor.py` | `ebc6cefb488551dee55134effecf333c86ba562b1299dd68dbc19489e2207a73` |
| `runtime/native_executor.py` | `d9d9fe6ea456ed8392797a9bc8fce6afb2fd469b4bd85efe38372fe72c5fb242` |
| `runtime/planning.py` | `2cc10479eb09cb368dbf17e745d7cf921d9bb0cd3d368d314d7ce2e4a614260e` |
| `runtime/native_validation.py` | `0a030d5fe452eb6de356976852401886a891947b155767d3341e8c49ec670736` |
| `api/application.py` | `6e33260d4528771e04e8aa2b4f99de838153d98a71ecaabf992501ad3e4f317b` |
| `api/turns.py` | `a41946c17bacec2834207de0e070817a36e26008a371c68157f21f51e0b9ce84` |
| `api/tasks.py` | `a3071d729fb41310230616c3ef1ee19c405e3ce177fc481cda8a79a77e246942` |

Final bounded result: **changes requested for the two assembly findings above**. No source repair, model invocation, production readiness claim, frozen-source claim, or separate architecture approval was made by this reviewer.
