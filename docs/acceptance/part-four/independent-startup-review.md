# Independent startup publication review

2026-10-15. Scoped read-only review of `startup_publication.py`, the opt-in `Recovery.recover(resume_publications=...)` branch, its application wiring, publish-only `AnswerPublisher` construction, and `test_startup_publication.py`. Existing publisher, bundle, state, operation and blob gates were read to trace their boundaries. No models, accounts or network were used; existing test batches were not rerun. This is one independent review lane, not an overall merge or real-provider qualification approval.

## Findings

1. **Published bundle shortcut could falsely report recovery success — fixed during review.** The original startup path treated any return from `BundlePublisher.publish()` as publication success. Its existing published-bundle branch returns a historical card without calling the supplied answer releaser (`documents/publish.py:227`). A still-READY task could consequently be reported as PUBLISHED without its transaction gates running. The revised startup code requires a VERIFIED bundle belonging to this task/attempt and then reads the committed task state before reporting success (`runtime/startup_publication.py:81`, `:91`). Root added an actual RED regression and the repair. An independent probe of the repaired path returned `blocked_local_publication`, actual state BLOCKED, with one existing answer event before and after.

2. **Malformed owner handoff escaped the rejection handler — fixed and independently reprobed.** With a non-null lease owner and `checkpoint.planning_handoff=[]`, the original `_ready()` and its exception handler both called `.get('workflow_owner')` on a list. An independent probe raised `AttributeError: 'list' object has no attribute 'get'` instead of safely deferring or blocking this task, preventing the entire local service from starting. The final shared `_owned()` validates the handoff shape (`runtime/startup_publication.py:13`); the failure handler also tolerates a malformed top-level checkpoint while retaining its original bytes (`:106`). Independent memory-copy probes of list/null handoffs now return `local_publication_deferred`, actual READY, preserving the foreign owner and checkpoint. A list checkpoint with no owner returns `blocked_local_publication`, actual BLOCKED, retaining the checkpoint bytes. No exception escaped.

## Other observed gates

- `Recovery.recover()` invokes the local publication path only for an uncancelled READY snapshot. Other states retain the existing recovery behavior. The new module imports publishers, not provider dispatchers or translation ports.
- `_ready()` requires the latest attempt and immutable contract version, rereads cancellation and ownership, and rejects a current request lacking a valid locally completed step binding. It does not turn remote-unknown work into a new request.
- Native and Claude answer publication retain their existing writer-transaction release approval, current dependency, A review, canonical/source-byte and incident checks. Claude startup calls `publish_in_transaction()` and requires no translation service; staging still explicitly requires one.
- File publication uses the existing complete bundle transaction and supplies an answer callback that rereads the current READY/cancellation/owner fences. The revised precheck prevents the historical bundle shortcut. Evidence roots are checked for reparse points and containment inside the data root.
- The final startup entry requires explicit real/fake provider mode and compares it with the immutable route's `test_only` marker before constructing a publisher (`runtime/startup_publication.py:45`). Application wiring supplies its actual configured mode; a fixture route cannot be resumed as a real publication.
- The inspected tests cover native replay without extra turns/model starts, damaged approval/review/evidence/source, cancellation, blocked publication, foreign owner, unknown current remote, a newer attempt, Claude local translation reuse with a Chinese-only published answer, and atomic file publication. Root owns execution of these tests; the independent lane did not rerun them.

## Independent probe method and limits

The probe opened an existing root-owned disposable test database using SQLite `mode=ro`, backed it up into a shared in-memory database, and redirected only the probe process's `Database.connect()` to that memory copy. Only memory records were changed. Original artifacts and evidence were read from their existing paths. No source, test, original database or artifact bytes were modified. The first attempt used an already-cleaned temporary path and failed to open; the subsequent probe selected a current existing fixture and exited 0.

Observed repaired-bundle result: `decision=blocked_local_publication`, reported/actual state BLOCKED, answer event count 1 before/after. Initial malformed-owner result: uncaught `AttributeError`. Final repaired-owner results: list/null handoff deferred with original foreign lease and bytes retained; malformed top-level checkpoint blocked with original bytes retained. These are corruption-boundary probes, not new provider executions or a substitute for root's broader regression.

The lane read root's `startup-final-v2-green.log`: 16 passed, one existing Starlette/httpx deprecation warning. That batch was not independently rerun. No unresolved actionable startup publication finding remained in the final reread and probes; broader regression, provider qualification and release approval remain root-owned.

## Final reviewed source hashes

| File | SHA-256 |
| --- | --- |
| `services/orchestrator/app/runtime/startup_publication.py` | `028FF9A84C744F2D57741AACA1449B75A968F8785F28D18D765A859BAD7D209B` |
| `services/orchestrator/app/runtime/recovery.py` | `AA90E0714251BB33667171D5D3051CBD225ABA9D5D7D4CEDA9C604751C712590` |
| `services/orchestrator/app/api/application.py` | `E022901A5F401B53022BDFAFE4C7620EA3DE67390930BEAE000FB59023961639` |
| `services/orchestrator/app/runtime/answer_publication.py` | `0F8A0392C569761DEE81837A2EECDCC9CA67225859186369236DCB6DE00E56F7` |
| `tests/integration/test_startup_publication.py` | `8C9BF7D7E656647008A060F2C7C2C7A5C241D57D8B97EEAF3F07E251B0B76807` |
