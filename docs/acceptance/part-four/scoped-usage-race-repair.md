# Failure usage receipt drain repair

2026-10-15. Bounded SOP S32 repair after root's final-v1/final-v2 regression exposed the existing `error_before_turn_completed` counterexample. Those full-run logs remain diagnostic evidence; they were not replaced or relabelled as passing. This lane changed only `scoped_codex_worker.py`, its source pin in `native_scope.py`, and `test_scoped_worker_repairs.py`. Root owns the final full regression; scope lane owns independent review. No external model, account, provider probe or network request was made.

## Root cause and final behavior

The local peer writes SSE identity records to stderr and protocol notifications/receipts to stdout. Independent reader threads do not preserve cross-pipe write order. The original invocation loop called `maybe_started()` only after a successful pump. If stdout's fatal notification arrived before stderr's `response.created`, the exception handler immediately emitted its one allowed started event with a null request reference. The later failure drain could consume a genuine completed model identity and its unique 33-token receipt, but `bound_usage()` correctly rejected it because the already-frozen started request reference was null. This explains why the same fixed fixture passed alone and intermittently failed in a full run; path length is not the cause of this receipt loss.

The final failure path requests interruption, closes the local peer and drains the existing reader queue before choosing its started fallback (`scoped_codex_worker.py:479`). A trusted complete drain may call `maybe_started()` once with the actual created response identifier before `bound_usage()` checks the receipt (`:407`). Only if no started event can be bound does the handler emit the existing null-reference fallback. Runtime consumers therefore see one stable started reference; they are never asked to replace a null start with a later identifier.

The drain rejects billing if a reader is still alive, a reader reports an output/truncation error, SSE parsing is invalid, identity is missing or ambiguous, the model differs, receipt count differs from one, or request/thread/turn references do not match. Reader liveness and error-sentinel checks are conservative because an incomplete stream cannot establish uniqueness. No timeout, sleep, retry or model request was added. Existing unknown-usage behavior is retained when proof is incomplete.

`ScopedCodexRuntime` was not relaxed. It still requires billing/capture references to match the single started event, checks actual model and identity source, allows only one bill and emits no business capture for this failure. Its existing `interrupt_ack` handling accepts acknowledgement before a started event; the later bound receipt remains failure cost evidence, never successful output or remote-stop confirmation.

## Actual evidence

| Evidence | Observed result |
| --- | --- |
| `scoped-usage-race-probe.py` / initial `.log` | Deterministic in-memory queue schedule, no subprocess/model: early stderr produced one usage; identical identity arriving during failure drain produced zero usage with a null frozen start. |
| `scoped-usage-race-red.log` | New deterministic contract: 1 failed, 6 passed; the valid delayed identity lost its receipt. |
| `scoped-usage-race-drain-boundary-red.log` | Two conservative-boundary counterexamples failed before the added guards: output-limit sentinel and unfinished reader could otherwise produce billing from an incomplete drain. |
| `scoped-usage-race-final-green.log` | Scoped worker/runtime/repair, source-bound scope, phase usage/bridge and usage-ledger tests: 220 passed in 46.37 s; one existing Starlette/httpx deprecation warning. |
| `scoped-usage-runtime-binding-green.log` | Two actual local-process fixtures passed: peer emits SSE only after receiving `turn/interrupt`; real worker and `ScopedCodexRuntime` preserve exactly one actual started reference plus one bound 33-token usage and no capture. |
| `scoped-usage-worker-final-green.log` | After the extra peer fixtures were added, all 38 worker repair contracts passed in 11.16 s. This rerun also checks the shared peer source has not regressed the prior negative cases. |
| `scoped-usage-race-probe-final.log` | Early and late identity schedules now both produce exactly one `resp_fixture`/`turn_fixture` started event, one matching usage record and no capture, while returning failure. |
| `scoped-usage-qualification-check.log` | Actual worker hash equals the source pin and policy manifest; prior and current policy hashes differ; newly constructed real-mode app without a backend factory has registry count 0. No model or probe calls were started. |

The 220-test batch and the later 38-test batch overlap and must not be summed as unique tests. The two added local-process fixtures were also run separately. Synthetic/local-peer outcomes do not establish live provider cancellation, recovery, billing availability or production qualification.

## Source pin and qualification boundary

The worker source changed, so its immutable source pin was synchronized instead of bypassed. Source-bound policy hash changed from `0185b80ede338a01c72758a26ae6a11f45ee7daa080cf1bc8ef7621282315c50` to `593dbcd62d8c99b616e45018a52270e9d543b4b66fc4a54f52d1c46baf455d85`. Old source-policy qualification is not inherited. The official entry, allowed controls, identity checks, single-turn policy, public contracts and empty production registry remain unchanged by this repair. Synchronizing a source hash is not new evidence qualifying a provider or entry.

Final frozen SHA-256:

| File | SHA-256 |
| --- | --- |
| `services/orchestrator/app/providers/scoped_codex_worker.py` | `92fd9440c70307c9c5b7e2c9be30489ea2c4454c760b086f06478d4f1b7210ab` |
| `services/orchestrator/app/providers/native_scope.py` | `D7CFC429A6FF51160379C35CFF00AAF38B1D883FBCBB8F74DFD99B12D1FA7613` |
| `tests/contracts/test_scoped_worker_repairs.py` | `B6626E68660690AF2CC3896D8A650269B4AD65FECD8DC85F8C9F145D2D775D18` |
