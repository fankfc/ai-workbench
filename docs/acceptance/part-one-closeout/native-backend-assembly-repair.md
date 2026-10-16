# Native backend assembly repair and lane freeze

2026-10-14. This follow-up implements the two findings in [independent review v2](C:/Users/asd15/Documents/ChatGPT/ai/docs/acceptance/part-one-closeout/native-assembly-independent-review-v2.md). The user subsequently requested that part one be frozen; this lane completed only the repairs already in progress and then stopped source changes.

Changed source is limited to `runtime/supervisor.py`, new `runtime/native_backend.py`, and new `tests/integration/test_native_backend_bindings.py`. Root-owned planning, phase bridge, scoped runtime, and worker files were not edited by this lane.

## Resulting behavior

`build_native_backend(planner, executor, *, provider_registry=None, allow_fixture=False)` creates private NativeBackendBindings from the actual bound planning/B/A runtime objects. Production assembly checks their supplied ProviderContracts, matching profile IDs, PhaseBridge bindings, classification, database/workspace association, and existing scope capability records. It derives the registry from these objects. Fixture assembly requires both explicit fixture opt-in and an explicit registry made from the bound fixture ports. Construction does not probe, authenticate, invoke, or register providers.

The binding's cancellation callback calls each distinct underlying planning/B/A runtime once and examines every result. Exceptions, False, an incomplete RpcCleanup, remaining processes/handles/temp directories, and unsupported nonempty results produce only `NATIVE_LOCAL_CLEANUP_UNCONFIRMED`. It does not pass through PhaseBridge.cancel, which discards the underlying return value. Successful local cleanup does not set `external_stop_confirmed` or prove remote stop.

On publication interruption, the supervisor now preserves READY only when the attempt is current and uncancelled, the dispatcher owns the recorded handoff, and the staged public release remains bound to the persisted approval/current revision/review. It retains the staged gate and marks publication pending without emitting a failure event for that valid READY result. Missing gates still block; cancelled/failed/published tasks, foreign owners, and superseded attempts retain their fences. The builder's publication callback also checks the current attempt and rejects a foreign lease before delegating to the existing executor/publisher checks.

The staged result can then be explicitly replayed through `bindings.publish(plan, result)` without further planning/B/A invocation. No automatic restart publication port was added, and this evidence does not establish automatic publication after an application restart or live provider readiness.

## Observed RED/GREEN evidence

- [Initial business RED](C:/Users/asd15/Documents/ChatGPT/ai/docs/acceptance/part-one-closeout/native-backend-bindings-red.log): **7 failed, 3 passed, exit 1**. The baseline used the former executor-only assembly callback. Failures demonstrated omitted planning cleanup, swallowed planning failure, READY becoming BLOCKED, publication through a foreign lease, and an old dispatcher changing a superseded attempt. Three existing cancellation/terminal/gate fences already passed.
- [Cleanup-result RED](C:/Users/asd15/Documents/ChatGPT/ai/docs/acceptance/part-one-closeout/native-backend-cleanup-results-red.log): **3 failed, 1 passed, exit 1**. This showed that combining through executor.cancel discarded B/A False results and repeated cleanup for one shared runtime. The final builder checks the distinct underlying runtime results directly.
- [Final bounded GREEN](C:/Users/asd15/Documents/ChatGPT/ai/docs/acceptance/part-one-closeout/native-backend-bindings-final-green.log): **135 passed, 1 warning in 16.39s, exit 0**. The command included the new backend bindings tests plus existing API, supervisor, planning, prepared workflow, native validation/publication, and recovery suites. The warning was the existing Starlette TestClient/httpx deprecation.
- A final standalone fixture probe returned `RpcCleanup(cleanup_complete=False, running=1)` from planning. The binding rejected it with the fixed cleanup error, and planning/B/A each received one cleanup call; **exit 0**. Its whitelisted result is preserved in the freeze JSON.

The assembled publication regression uses the actual local planner/storage/workflow/executor/publisher and NativeRegistryValidator's Python AST check on immutable candidate bytes. Its A/B captures remain explicit fixtures. It stages READY, interrupts publication, replays publication twice, and observes exactly one public answer with one planning/B/A start each. It does not substitute an always-True mechanical validator. Separate construction tests use synthetic supplied production records to test local binding/qualification/revocation logic; they do not qualify a real model connection.

## Frozen lane source

The [freeze manifest](C:/Users/asd15/Documents/ChatGPT/ai/docs/acceptance/part-one-closeout/native-backend-repair-freeze.json) was written at **2026-10-14T07:28:47.666517Z**, after the final GREEN and cleanup receipt probe. It contains the exact command, observed result, zero external operation counts, and these hashes:

| File | SHA-256 |
| --- | --- |
| `services/orchestrator/app/runtime/supervisor.py` | `4367eb986fa6af34b554cd027958c504b13c1bfd60d1ad8c27279657b2166f50` |
| `services/orchestrator/app/runtime/native_backend.py` | `d102a34d1e124989d812166a575e0e2953c231c3c378505e3ebc6c27de9d827e` |
| `tests/integration/test_native_backend_bindings.py` | `069e8249364a4ab96b563214c2e36bcbe1b6607e3e594fe24d632dbe41ca1bc0` |

This freeze covers only this lane's three owned source files. It is not a whole-repository snapshot or a separate architecture approval. No models, installed native CLI, account/auth operations, or network calls were performed. Historical failed logs and the before-fix v2 review remain preserved. Further implementation and integration are deferred to the user's final consolidation.
