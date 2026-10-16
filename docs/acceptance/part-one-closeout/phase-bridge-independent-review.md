# Phase bridge and cumulative consumer independent review

No actionable defect was found in the bounded specification/quality scope reviewed on 2026-10-14. This reviewer authored neither phase_bridge.py nor root's cumulative consumer change. The review read the closeout work order, runtime integration gap, frozen implementation/tests, Workflow consumer and UsageLedger. It did not modify their source or rerun the author's 44/157 passing tests. This is an independent bounded review, not formal merge approval or real-provider qualification.

Source evidence supports the intended boundaries: the bridge rejects unknown identity, wrong A/B adapter/family, boolean scope claims and capabilities which return booleans. Exact request/contract/role bindings are checked before runtime start. Captured native identity/connection must equal the pinned private ProviderContract. It emits accepted references promptly, holds candidate/review events until clean iterator EOF, and rechecks prompt bytes and scope before deriving a business event. It grants neither publication nor authenticated canonical authorship. Relevant phase_bridge.py functions: _binding, _candidate, _review, _usage, _capability and run.

Six new independent probes passed. [The QA probe](../../../.tools/review-phase-bridge.py) writes only temporary files/databases; [recorded results](phase-bridge-independent-review.json) preserve actual observations and before/after source hashes:

- Changing source content and its self-declared SHA while the contract keeps the original input hash is rejected.
- Rehashing a changed mechanical proof cannot change its verifier from C to A.
- A real hardlink to the prompt is rejected before runtime start.
- Mutating the original raw usage mapping after capture construction does not change the consumed observation.
- Changing accounting mode inside one capture blocks candidate/review completion.
- A new actual API/Workflow/SQLite fixture exercises gapped cumulative cursors for A and B using the same scope string. Profile namespaces remain separate: B counters 30 to 75 allocate 30+45, A counters 10 to 25 allocate 10+15. Four measured fixture starts equal four stored steps; ledger total is 100, rather than summing snapshots to 140.

The cumulative consumer at workflow.py lines 437-449 now forwards cumulative_scope and uses validated native receipt_sequence with the pending-reservation offset. UsageLedger consumes differences in the provider-profile/scope namespace. Original receipt IDs remain in internal event audit; ledger local invocation/event keys stay distinct. Missing observations remain unknown, and invalid scoped sequences stop continuation. Candidate/review model JSON cannot supply billing.

All five reviewed source/test hashes stayed unchanged through the probes; both files in the phase author's frozen manifest match. The only warning was the existing Starlette/httpx deprecation. External responses and reported token counters in the API fixture are synthetic; local API, bytes, Workflow and SQLite execute. There were zero real provider/model calls and no actual-billing claim.

An enforcing runtime must still supply genuine scope capability and observed provider metadata, collect approved artifact bytes and protect immutable source/evidence paths. This bridge does not issue that capability or establish sandboxing, account authorization, native cancellation or real A/B connectivity. Current ZCode host-context and real-provider gates remain valid. Own ZCode metadata implementation/tests are outside this independent quality conclusion.
