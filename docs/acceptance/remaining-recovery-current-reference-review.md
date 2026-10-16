# Independent review of D012 current-step remote binding

Bounded read-only review passed on 2026-10-13. No actionable defect was found in the requested current-map scope. The reviewer is independent of the D012 implementation author. This is a limited independent review, not formal merge approval or real-provider qualification.

The [independent probe](../../.tools/review-current-recovery.py) ran the frozen Recovery implementation against temporary, real SQLite databases. [Recorded results](remaining-recovery-current-reference-review.json) contain **16/16 passing checks**, before/after source hashes, zero published outbox events and zero real-provider starts. All **101** source and lock hashes match [the final freeze](backend-source-hashes.json). Production, test, schema and lock files were not modified; the whole suite was not rerun.

The checks establish these observations:

- Query and observation receive the actual current B profile and its remote request/execution identifiers, including cases with only one identifier. The frozen A profile and first request remain unchanged in the task row.
- An accepted current request with no remote identifiers becomes unknown and blocked, including when stale main-row identifiers exist. No remote callback runs.
- Mismatched role, contract version, execution column, mirrored step checkpoint, missing step or invalid acceptance flag blocks before any query, observer or verifier callback.
- Switching to a new current step during query prevents the old verifier call. Switching during verification prevents applying the old completion in the final transaction. Both preserve the new step and the executing state.
- Three D014 serialized task/step records—accepted disconnect, cancellation after accepted missing identifiers, and completed A/B requests—follow the current binding. The completed case uses the latest A request, rather than the earlier B request stored in the main row.

The D014 replay reconstructed the recorded task/step bytes and synthesized only prerequisite conversation/provider/turn rows in a disposable database. It did not run a new Workflow, query a real provider, verify actual recovered artifact bytes, or establish cancellation/resume support. The injected completion verifier returns true solely to exercise callback and transaction fencing. An initial harness attempt to update immutable step identity was rejected by `STEP_REQUEST_IMMUTABLE`; the final malformed-binding fixtures use checkpoint mismatch or a separately inserted invalid association.

This review supplements [the earlier storage/recovery review](remaining-storage-recovery-review.md). Existing recovery/crash evidence and the root's final 780-pass test run retain their original scope.
