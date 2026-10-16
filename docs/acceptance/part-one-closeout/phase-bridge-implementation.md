# Native phase bridge implementation

Implemented only `services/orchestrator/app/providers/phase_bridge.py` and `tests/contracts/test_phase_bridge.py`, with this report and command evidence. No adapter, workflow, publisher, API, shared schema, dependency or account configuration was changed by this lane. No commit, model call, native launch, UI/account operation or network request was performed.

The bridge converts a trusted runtime's private native result into the existing Workflow interfaces: `artifact.candidate`, `review.decision`, and `provider.usage` containing raw/source/mode. It emits no model.delta, public message, answer, approval, canonical-authorship check or publication authority. `provider.completed` means that the native stream and phase protocol passed validation; C evidence, A decision and D018 publication gates still apply.

## Runtime interface for later production assembly

`PhaseBridge(runtime, provider: ProviderContract)` implements the existing run/probe/cancel shape. It requires an executable native ProviderContract with exact adapter/family `codex/gpt` for A and `zcode/glm` for B, and an AgentRequest whose identity matches it. Unknown/mismatched/unsupported identities, wrong role, missing scope capability, bool-only scope flags and invalid request binding produce a fixed provider.error with zero runtime starts.

The private runtime must implement:

```python
runtime.scope_capability.require_verified(provider) -> None
runtime.scope_capability.authorize(request, binding) -> None
runtime.run(request, binding) -> AsyncIterator[PhaseStarted | PhaseCapture]
runtime.cancel(task_id, attempt_id)       # supported cancellation only
runtime.probe() -> ProviderIdentity       # optional verified read-only identity port
```

The capability methods are synchronous verification/enforcement ports. They must raise for unavailable, stale, unenforced or revoked capability; returning True/False does not count as proof. PhaseBridge ignores runtime.scope_enforced configuration flags and derives its compatibility property only through require_verified. Every call authorizes its exact role/paths/binding before runtime.run, and rechecks capability/authorization before a business event is emitted. No real capability issuer was created here: production runtime assembly must supply the actual enforcement/verifier. Trusted server code cannot make a scope claim merely by attaching the property; a malicious issuer that lies is outside the trusted-port contract, and this bridge is not an OS sandbox.

PhaseBinding is a frozen private record containing request_id, phase, validated TaskContract, deeply read-only evidence_package, evidence_root and the exact prompt byte SHA. request_id is the service-owned prompt filename stem (the existing Workflow step UUID). The prompt is read from the supplied role workspace, rejects links/reparse/hardlinks/oversize content, and strictly has `{phase,contract,evidence_package}`. Contract task/attempt/version and phase/role are checked before launch. Native family must be GPT and there must be one deliverable; unsupported multi-file/Claude routes remain blocked. The prompt is re-read after the native iterator ends and any byte change rejects the result.

`PhaseStarted(local_request_id, external_request_id, external_execution_id)` is the first accepted record and immediately produces provider.started. The runtime must emit it promptly on actual acceptance, rather than defer it until final capture. Actual refs remain distinct from the service local step ID. Two missing refs retain an accepted audit event then error REMOTE_REFERENCE_REQUIRED; they never produce a candidate/completion. Identical repeated started records are no-ops; changed refs or started after the final capture fail.

`PhaseCapture` fields:

| Field | Meaning |
| --- | --- |
| local_request_id | Exact service step/invocation binding. |
| observed_provider: ProviderContract | Trusted actual response identity/connection metadata; must exactly match the pinned contract. Configured model selection or model prose is insufficient. |
| final_text: str or None | Original complete private final JSON. Hidden from repr and never reconstructed from redacted deltas. |
| external_request_id / external_execution_id | Exact match with accepted started record. |
| usage_receipts: tuple[UsageReceipt,...] | Independent native billing observations. Tuple-copied; raw mappings are deeply copied/read-only. |
| actual_artifacts: Mapping[str,bytes] | Independently collected approved artifact bytes, copied/read-only. The runtime owns actual path/scope collection. |
| exit_code / finished | Exact zero integer exit and true bool finish required. Bool exit values are rejected. |

Exactly one final capture and clean iterator EOF are required. Candidate/review output is held until EOF, prompt/capability rechecks and actual evidence checks; a second final capture, post-capture transport failure, changed prompt or revoked scope cannot expose an earlier candidate. Accepted records and usable usage observations can precede a fixed error, allowing existing Workflow to preserve uncertain remote work and incurred usage. The bridge never fabricates stop confirmation or retries a native request.

## Candidate response protocol

Execution/takeover raw final JSON must contain exactly the following known fields, with no provider-added PASS/approval attributes:

```json
{
  "schema_version":"1.0",
  "phase":"execution",
  "request_id":"<service step UUID>",
  "task_id":"<current task>",
  "attempt_id":"<current attempt>",
  "contract_version":"1.0",
  "contract_sha256":"<exact service-provided contract digest>",
  "deliverable_id":"<one contracted target>",
  "language":"zh-CN",
  "content":"<original complete candidate content>"
}
```

For inline text, the bridge takes content only from private complete final JSON and computes the actual UTF-8 SHA. Optional byte_sha256, if supplied, must equal it; the model is not required to compute an arbitrary hash. For an independently produced file, content must be absent and artifact_ref plus byte_sha256 are required. artifact_ref must exactly equal the contracted write_scope and be the only actual_artifacts entry; bytes must exist, be nonempty UTF-8 and match the claimed hash. Inline content and artifact_ref cannot both be used. Secret-looking literal strings in approved content remain byte exact; audit redaction cannot silently alter canonical content.

The emitted internal candidate has text/language, computed byte_sha256, contract digest, raw-response hash and content_source. It does not confer A authorship or issue the trusted A.canonical provenance record. Only the existing service-controlled artifact/version path registers immutable bytes.

## Review response protocol

Review uses the same schema/phase/request/task/attempt/version/contract digest fields, with phase=review, plus these required fields:

```json
{
  "revision_id":"<actual current revision>",
  "byte_sha256":"<actual candidate byte SHA supplied by service>",
  "decision":"PASS",
  "criterion_results":{"<A criterion ID>":true},
  "read_unit_ids":["<current source unit>"],
  "source_refs":["<current source ref>"],
  "evidence_refs":["<actual C proof filename>"],
  "issues":[],
  "sampling_note":null
}
```

Allowed decisions remain PASS/REPAIR/NEED_EVIDENCE/BLOCKED. The trusted request package must include actual artifact_path, revision_id, byte_sha256, candidate_content, mechanical_evidence and complete source context. The bridge reads actual candidate bytes and current proof files after EOF; all file/content/digest/revision/criterion/verifier/pass bindings must match. It verifies source bytes against contract input hashes and exact source refs. The model may report only A criterion results, cannot score C/human criteria, cannot introduce foreign refs or duplicate units, and cannot claim canonical authorship via extra fields. PASS additionally requires mandatory C proof passing, mandatory A result true, no open issues and complete read units when contracted. The emitted review.decision remains subject to Workflow.evaluate_review and publication verification.

## Usage receipts and existing consumer

`UsageReceipt(event_id, sequence, raw, source='reported', mode='request_total', cumulative_scope=None)` contains actual runtime observation, never model JSON assertions. Receipt IDs/sequences/types/counts are validated with D015 normalization. Identical receipt/sequence repeats are skipped; changed same-ID/sequence payloads, unordered new sequences or changing accounting modes reject. Missing/partial unobserved usage stays unknown/null rather than zero. The event payload preserves raw/source/mode and receipt_event_id/receipt_sequence, plus cumulative_scope when present. All three supported modes remain available; numeric subset/negative/bool counter errors fail.

Root separately repaired the existing Workflow consumer to forward cumulative_scope and use the actual global receipt_sequence for scoped cumulative allocation. Its independent RED proved cross-request counters 30→50 previously billed80; this bridge's positive test retains scope and sequence101. The earlier phase-bridge-red-stream.log includes a temporary unsupported-port expectation while that consumer was missing; the final protocol preserves scoped cumulative receipts after the consumer fix. No workflow file was changed by this lane.

## Verification and evidence

| Command stage | Outcome |
| --- | --- |
| Importable scaffold + 31 business tests, phase-bridge-red.log | 31 failed, pytest exit1. No import/collection failure was used as behavior RED. |
| Initial implementation, phase-bridge-green-first.log | 31 passed, exit0, 0.54s. |
| Stream/refs/scope/prompt/temporary cumulative-port additions, phase-bridge-red-stream.log | 5 failed, 36 passed, exit1. |
| Explicit GPT-for-B substitution, phase-bridge-red-role.log | 1 failed, 41 deselected, exit1; fixed to pre-start role rejection. |
| Actual candidate damage / evidence changed after final capture, phase-bridge-red-final-evidence.log | 2 failed, 42 passed, exit1. |
| Final owned scope, phase-bridge-green.log / phase-bridge-tests.xml | 44 passed, pytest exit0, 1.22s. |
| Phase + existing GPT/ZCode adapters + workflow + ledger, phase-bridge-consumers-green.log | 157 passed, pytest exit0, 86.82s; one existing Starlette/httpx deprecation warning. |

Owned command:

```powershell
services/orchestrator/.venv/Scripts/python.exe -m pytest tests/contracts/test_phase_bridge.py -q --junitxml=docs/acceptance/part-one-closeout/phase-bridge-tests.xml
```

Targeted existing-adapter/workflow/ledger command:

```powershell
services/orchestrator/.venv/Scripts/python.exe -m pytest tests/contracts/test_phase_bridge.py tests/contracts/test_gpt_adapter.py tests/contracts/test_zcode_adapter.py tests/integration/test_agent_workflow.py tests/unit/test_usage_ledger.py -q
```

Its output and actual pytest exit are saved in phase-bridge-consumers-green.log. The first attempt used a nonexistent integration/test_usage_ledger.py path and ran zero tests with exit4; phase-bridge-consumers-path-error.log is retained. The corrected command uses tests/unit/test_usage_ledger.py; the path error is tooling evidence, not a business RED or product failure. phase-bridge-source-hashes.json records the two frozen owned files and command outcomes.

All scope/capture fixtures explicitly use a supplied in-memory runtime. The fixture verifier certifies only that no external executor exists in that test; it does not verify actual Codex/ZCode isolation or identity. Production connection/capability gates remain fail closed until supported actual metadata and enforcing runtime are supplied. This implementation completes only the bridge and its local contract checks, not the real provider handoff or the second-part product.

An independent other-author review subsequently ran six new hostile schedules, with all six passing and owned source/test hashes unchanged. phase-bridge-independent-review.json preserves wrong source-content/self-hash rejection against the actual contract, self-hashed C proof/verifier tampering, hardlinked prompt pre-start rejection, original receipt mutation isolation, mode-change blocking and actual API/Workflow/SQLite scoped cumulative allocation across gapped cursors/two profile namespaces. Model counters and billing in that last case are explicitly synthetic. This author inherits that external review; it does not certify its own implementation or declare formal merge approval.
