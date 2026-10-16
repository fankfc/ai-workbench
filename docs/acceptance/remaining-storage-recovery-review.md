# Independent read-only review: D008 / D010 / D012

Scope: `storage/database.py`, `migrations.py`, `blobs.py`, `schema/0001_initial.sql`; `runtime/state_machine.py`, outbox transaction/identity/crash behavior; `runtime/recovery.py`; corresponding storage/state/outbox/recovery tests and frozen acceptance evidence. No production file was changed by this reviewer. D016/D019, which this reviewer authored, are excluded. The concurrently repaired raw-PublicEvent transport authority segment was not substituted for an independent review; its three crash windows were rechecked after the author reported it stable.

Verdict at initial review: **REQUEST CHANGES — two HIGH recovery defects reproduced.** D008 and the scoped D010 transaction/gate checks had no additional actionable defect found in this bounded review. This is a single independent implementation review, not merge approval. The code-review skill requires independent reviewer and architect lanes for APPROVE; all four concurrency slots were occupied, so the additional lanes were unavailable. `independent review unavailable` remains explicit; no merge-ready or formal APPROVE claim is made.

## HIGH — remote reconciliation can resurrect a terminal attempt

Original locations: `services/orchestrator/app/runtime/recovery.py:59` and `:92`. The pre-verifier check excludes cancellation but does not exclude `FAILED` or `PUBLISHED`; the later writer branch handles `completed` by assigning `VALIDATING` to any state outside the validation/review/output/ready list. A task can become terminal while the remote query is running. The callback is then invoked with the terminal row and the terminal state is overwritten.

Both cases were reproduced on independent temporary real SQLite databases: query callback updates the current attempt to FAILED or PUBLISHED and returns completed; completion verifier returns True. The verifier receives the terminal state and the final database state becomes VALIDATING. This can resume a failed task or remove the published-state proof for an already delivered answer. The existing cancel-during-query test does not cover these terminal states.

Required fix: recheck all terminal states before completion/observer callbacks and again inside the writer transaction before applying any remote status. Preserve terminal state and record a fixed terminal/stale reconciliation decision. Add tests for FAILED/PUBLISHED created during query and during verification, including unknown/running/completed responses. Source/query races must not revive a finished attempt.

## HIGH — out-of-order stable duplicates erase an already received sequence

Original location: `services/orchestrator/app/runtime/recovery.py:164`–`:169`. The known stable-key branch advances only a duplicate arriving at `last+1`. A duplicate with a higher sequence is neither buffered nor recorded as an acknowledged no-op.

Reproduction: receive sequence 1 with stable key `stable`; receive sequence 3 with the same key and same payload; receive completion sequence 4; receive distinct sequence 2. Sequence 3 is reported duplicate but discarded. The final provider counter is 2, completion 4 remains buffered, and state remains EXECUTING. All four sequence positions have already arrived, but the controller now needs another replay of sequence 3 to close a gap it created itself.

Required fix: retain known semantic duplicates arriving beyond the next expected sequence as buffered sequence/no-op acknowledgments. Draining after sequence 2 must consume sequence 3 without applying its semantic payload again, then consume completion 4. Test restart between receipt and drain, and retain duplicate-conflict rejection.

The author was notified of both reproductions and confirmed the root causes. Original evidence is frozen at `remaining-storage-recovery-reproductions.json`; `.tools/review-storage-recovery.py` accepts a separate new filename for a post-fix replay and refuses to overwrite prior evidence.

## Evidence and coverage

The fresh storage/state/recovery regression command passed **195 tests in 15.79 s**. These green tests did not cover the two new hostile schedules above; passing the prior suite is not used to dismiss either finding. Storage verification covers actual SQLite write locks, transactional migration rollback, content hashing, interrupted writes, immutable registrations and preservation of prior data. Fault injections for disk-full/write errors are explicitly injections; hardware power-loss guarantees are not inferred.

State changes and outbox registration share BEGIN IMMEDIATE and roll back together on inserted-event failure. Current attempt, contract version, expected state, cancellation and persisted release-gate bindings are checked. Release-gate registration is a trusted service helper; actual A review/current graph/blob publication authority belongs to the later D013/D016/D018/D020 consumers, and must not be granted to model text or arbitrary user payloads.

The three real child-process crash tests were freshly rerun: **3 passed, 10 deselected in 1.40 s**. Source inspection confirms `os._exit(81/82/83)` at before commit, after commit/before dispatch and after send/before acknowledgment. Independent read-only opening of all three frozen databases/receivers matched the reports: before-commit retains RECEIVED with no events; the other two retain INPUT_PREPARING, two events, exactly one persisted receiver entry and no remaining pending events after recovery. Receiver IDs are unique and belong to actual database events. `remaining-storage-crash-checks.json` and `remaining-storage-crash-recheck.log` preserve this evidence.

Existing recovery unknown/query-error behavior remains blocked, preserves external IDs, invokes no new-request callback and logs only the exception class. Sequential duplicates, normal gaps, cancellation, buffered failure and transaction rollback have targeted tests. Actual remote provider reconnection, shared account/session behavior and remote stop are outside these local fixtures and remain unverified in D004–D006.

Review reproductions use temporary databases and no model calls. The initial findings and evidence above remain preserved.

## Post-fix independent recheck

Both HIGH findings are now **resolved in the bounded implementation review**. The author added four failing tests before changing production behavior, then reported 27 recovery tests green. This reviewer independently inspected the new pre-callback and final-writer terminal guards and the buffered stable-duplicate no-op behavior, reran the unchanged original hostile schedules into a new file, and ran the recovery suite: **27 passed in 1.05 s**.

`remaining-storage-recovery-postfix.json` records FAILED/PUBLISHED retained with no completion verifier callbacks, and the out-of-order stable-duplicate sequence advancing to 4 with semantic effects exactly `[1,2,4]`, empty buffer and VALIDATING. The original before-fix JSON was not overwritten. The author's separate verifier-internal terminal-transition regression also passes. `remaining-storage-recovery-postfix.log` records the fresh test output.

No additional actionable finding remains in this reviewed D008/D010/D012 scope. This is a bounded single independent review with repair confirmation; it does not replace an architect lane or constitute formal merge approval. The full two-lane merge-readiness gate remains unavailable in this session, as stated above. Current product release authority still relies on D013/D016/D018/D020 and real provider enablement remains blocked by the separate D004–D006 findings.
