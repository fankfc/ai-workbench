# Final D020 / publisher integration review

Read-only scope: D020 scenario_driver and backend_vertical tests, D018 NativePublisher/public_projection/native-publication tests, task contracts/usage dependencies, and D014 request boundaries consumed by the integration driver. Production code was not edited in this review lane; all reproductions used isolated local API/SQLite/evidence and synthetic provider streams. Separate D008/D010/D012 authoring changes were reviewed by another agent.

## Publisher finding and closure

One new **HIGH** was reproduced after the earlier four root fixes: stage correctly bound its A review, but publish re-evaluated a self-consistent review without binding it again to the staged task/route/revision/pinned contract. Five temporary database variants all published one answer before repair: decision revision rev2 over staged rev1, foreign task, foreign route, newly requiring A canonical content over a B artifact, and changed budget while the pinned contract remained unchanged.

The root author added RED tests and a shared review-snapshot verifier. The independent original five-case probe was rerun with `--postfix` and all five now block with zero published answers. Original remaining-final-publisher-evidence.json is preserved; remaining-final-publisher-evidence-postfix.json and its log record new source hashes and actual reason codes. The verifier checks the frozen task contract/digest and full review snapshot, actual task/attempt/route/revision, required canonical provenance, current evidence bytes and the stage snapshot before writing publication. This recorded finding is resolved for the tested snapshot.

The prior four findings remain independently closed: original fake answer rows do not become visible after a real publish; canonical claims cannot relabel B content; repeated same-sequence delta bills stay idempotent; genuine prior publications retain their frozen version when a new attempt exists. Public history uses the actual publication event/registered snapshot, and all outbox transports use the same projector rather than treating a schema declaration as authority.

## Workflow stream findings and closure

Three additional **HIGH** integration boundaries were reproduced in remaining-workflow-stream-evidence.json:

- A GPT task with a Claude B profile started once with Chinese source bytes before the eventual block, because the request gate used only the A/task model family.
- A compliant provider.started event with actual request/execution references followed by known usage and an observation ConnectionError started three new invocations and did not persist those execution references in task/step columns.
- The same observation-loss stream could start three invocations after the task became FAILED.

After the D014 author repaired these branches, the exact original three scenarios were independently rerun. B Claude now has zero starts and no original Chinese prompt. Accepted remote observation loss has one start, status UNKNOWN_REMOTE, a BLOCKED task and matching actual task/step/current-map references. FAILED has one start and remains FAILED. Before evidence is untouched; postfix JSON/log contain actual observed references and source hashes. All three recorded findings are resolved for that snapshot.

The current-reference map also required a D012 consumer change. That owner added seven effective RED cases and obtained 34 passing recovery tests: cross-check current step/profile/role/version/ref before a callback, use actual current B/A profile/IDs while retaining frozen A identity, block accepted calls without refs without querying stale compatibility columns, and refuse old completion after step changes. Another author completed the final independent read-only review: remaining-recovery-current-reference-review.json records **16/16 experiments passed**, including actual D014 row replay, request-only/execution-only references, damaged step bindings and query/verifier step changes. Source/test hashes and all 101 root-frozen source files match, with zero real model starts or publications. This reviewer does not certify its own implementation.

## D020 exercised boundary

Fresh scoped command:

```powershell
services/orchestrator/.venv/Scripts/python.exe -m pytest tests/integration/test_native_publication.py tests/integration/test_public_projection.py tests/integration/test_backend_vertical.py -q
```

Observed **46 passed, 1 deselected, exit 0**, with one existing Starlette TestClient httpx deprecation warning. The final D020 portion covers four domain cases and eleven fault cases plus the aggregate vertical runner (root editorial count correction: 13 publisher + 17 projection + 16 vertical = 46; original logs are unchanged). It calls the production API/storage/workflow/validators/ledger/publisher/projector, saves actual databases/blobs/evidence and records fixture provider start counters and usage. Fixed trusted code/data execution remains restricted to test fixtures. Missing evidence, cancellation, unknown restart, stale approval, duplicate requests, budget, connection failure and the unavailable Claude gate retain explicit non-publication outcomes.

The driver requires explicit provider_mode=fake; the real-provider test is deselected by default and refuses to treat fixture output as real handoff. Outputs carry provider_boundary=fake, real_provider_verified=false and real_handoff_complete=false. Synthetic A decisions/usage and local mechanical tests establish local integration behavior, not actual model quality, subscription cost or real CLI readiness. Startup production recovery still uses a conservative unknown callback; real query/observe/verification are injection ports, not connected production capability.

The later frozen mixed helper and final D014 dependency/profile/lease additions received an additional targeted independent review. The fresh command included both mixed-pipeline and backend-vertical files with `-k 'mixed or upstream or budget_after_repair'`: **8 passed, 14 deselected, exit 0, 6.74 s**, comprising five helper tests plus mixed normal, upstream change and repair-budget integration cases. Ten inspected source/test hashes were identical before and after. remaining-final-d20-evidence.json and remaining-final-d20-tests.log preserve the command, JUnit path and actual isolated database observations.

Read-only SQLite/blob inspection checked scenario candidate/turn/request counts against actual rows, recomputed every graph artifact's hash and matched immutable dependency references to graph references. The published mixed case contains exactly data→analysis→result→figure plus an answer depending on result and figure; all five versions are current. Actual CSV bytes are 1/2/3, result sum=6 binds the source hash, and the three-bar SVG binds the actual result hash. Changing the data version makes analysis/result/figure/answer stale and leaves zero answers. Budget exhaustion after repair retains two candidates, three provider starts/three durable request rows and 45 fixture tokens, then blocks with no answer.

The independent evidence extractor's first attempt used the wrong table name usage_events after its eight tests had passed; that instrumentation error was corrected to the actual usage_entries request table. The first test log is retained as remaining-final-d20-tests-first.log, and the successful rerun and actual database verification are separately recorded. This was a reviewer-runner error, not a product failure or business RED result.

No further actionable issue was found in this targeted frozen D020 review. No unsupported language, canonical document, OS sandbox or real-provider capability is declared passed by this review. Parent finalization owns the full frozen aggregate and later real-provider acceptance gates.

All specifically recorded publisher/workflow findings above are closed at their postfix snapshots. This is an independent bounded code review and fix verification, not a formal whole-change merge APPROVE; the platform's native thread limit prevented a separate architecture-agent launch. Parent finalization must verify source hashes at test start/end and attach final frozen integration evidence.
