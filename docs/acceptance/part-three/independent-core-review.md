# Independent core review — phase three

Reviewed 2026-10-14 by an independent review agent. Scope: D051 backup/restore engine, authenticated API and desktop IPC/preload/settings integration; production A-led selection in `native_backend.py`/`workflow.py`; joint qualification evaluator. Read the D051/D046 requirements, relevant integration/storage tests, managed backend restart implementation, recovery and publication reference checks. Ongoing release/operations controller changes were excluded.

## Finding requiring correction

**P2 — Require database-referenced source inputs even when the archive omits its source manifest.** `services/orchestrator/app/storage/backup.py:162–170` verifies only source manifests found by a filesystem glob. A missing source manifest therefore removes its entire input set from validation. The portable manifest is untrusted and can be rewritten, so its file list cannot establish input completeness. A paused task can retain its input reference/hash in the database while restore reports `verified=true` and switches to a root missing that source. Original live data remains preserved, but the restored task is incomplete.

Targeted adversarial reproduction, using only an isolated temporary root and fake app:

1. Create a conversation and turn; mark its task PAUSED.
2. Ingest `input/material.txt` through WorkspaceManager with bytes `irreplaceable source`.
3. Retain `checkpoint.task_contract.inputs` with `id=SOURCE-1`, `ref=input/material.txt` and the original SHA-256. The minimal reproduction populates only the relevant inputs portion of the contract; it does not claim to simulate a complete planned task.
4. Create a normal backup. Delete the backup task's `.source-manifest.json` and `input/material.txt`; remove their two outer manifest entries, leaving the database untouched.
5. Call `validate_backup`, then `restore_backup` against the original live root.

Observed result (Python process exit 0):

```json
{"database_source_reference_retained":true,"validate_verified":true,"restore_verified":true,"restored_source_exists":false}
```

Correction: derive mandatory input/source paths and hashes from persisted task/planning context, require the matching source manifest and bytes, and reject disagreement or omission before restore succeeds. Add a regression with an actual complete contract and a rewritten outer manifest. Reported to the root and backup owner; correction/reverification is pending as of this report.

## Other inspected boundaries

No additional important finding established in the reviewed A-led selection, same-A request binding, usage reservation, cancellation reuse, or desktop opaque-reference flow. Production A-led initial candidates and subsequent repairs use role A; fixture collaboration remains separate. This is static review evidence, not a real-provider qualification result.

The backup engine uses SQLite online backup under a writer fence, validates schema SQL/history, rejects path traversal/reparse links and duplicate ZIP names, verifies published bundle references, and retains the live root during copy/migration. The desktop restart path persists the verified destination and has a previous-root fallback. These observations do not waive the source-completeness defect above.

## Limits and recommendation

Recommendation: **REQUEST CHANGES** for the confirmed P2 until corrected and independently rechecked. This is one bounded independent review lane, not an overall merge-ready approval or two-lane architectural sign-off. Full regression was intentionally not rerun because the root agent owns the fresh run. No real model calls, installation, signing, distribution, or external messages occurred. Real-provider identity/usage, human review, signed Windows installation/update and external evaluation remain outside this local review.

## Independent revalidation after correction

The backup owner added database-derived source closure in `verify_task_sources`. Independently reran the exact five-step omission reproduction above against the corrected code, preserving the same database input reference and rewriting the outer manifest after deleting both source bytes and the per-task source manifest. Both operations now reject the package. Python process exited 0 with explicit assertions:

```json
{"validate":"BACKUP_SOURCE_MANIFEST_MISSING","restore":"BACKUP_SOURCE_MANIFEST_MISSING","source_retained":true,"restored_directories":0}
```

The confirmed P2 is **closed by this targeted revalidation**. No remaining important finding was established within the original bounded core scope. The historical REQUEST CHANGES recommendation above records the pre-fix state; it does not describe the corrected omission behavior. Full-suite results remain owned by the root agent.

A separate, limited read-only operations check confirmed that persistent incident checks are called in the common state-machine release fences and inside `BundlePublisher.publish`'s transaction. This was not a comprehensive review of the new operations controller. Scope watch: `requalify` records one configuration under a domain, while the publication check removes the entire requalified domain from the frozen set; before enabling real requalification, verify that narrower difficulty/profile qualification cannot thaw unqualified configurations. No external qualification or requalification was executed here.

## Operations scope follow-up review

Reviewed the subsequent correction in `operations/controller.py`, both `register_release_gate` and `validate_release_gate` in `runtime/state_machine.py`, the explicit guard in `documents/publish.py`, and `tests/operations/test_persistent_controls.py`. The domain-wide thaw watch is resolved in the inspected implementation: incidents stay open, stored exceptions are indexed by qualification key and full configuration, and publication recomputes the key and requires exact configuration equality plus the task domain. Unmatched difficulty, profile, provider/policy configuration or missing service checkpoint remains frozen. Previous invalidated keys remain blocked by route selection and cannot be requalified through the public controller method. Multiple applicable incidents are checked individually.

The controller persists incident state in existing desktop settings; normal preferences updates use a typed patch rather than exposing arbitrary operations-state replacement. Incident blob hashes remain visible to the existing reference collector. The reviewed tests cover restart persistence, actual publisher freeze, stale evidence rejection, easy-versus-hard separation, real translation cache-row invalidation with a test-only provider fixture, collector protection and configurable retention. Tests were inspected rather than rerun in this lane; the owning/root agents retain responsibility for fresh execution results.

No additional important residual finding established in this bounded operations follow-up. Real requalification remains unexecuted and production currently lacks a qualified configuration writer; absence of that checkpoint fails closed. Update-coordinator work was excluded because it was still being implemented by a separate owner.
