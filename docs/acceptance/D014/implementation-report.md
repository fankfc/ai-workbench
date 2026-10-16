# D014 implementation record

Status: implemented and fixture-verified; publication is a separate gate.

`services/orchestrator/.venv/Scripts/python.exe -m pytest tests/integration/test_agent_workflow.py -q`
passed 55 tests with exit 0. The existing Starlette/httpx deprecation warning is
preserved; dependencies were not changed. Initial importable Workflow.run stub
produced 12 behavior failures (red.txt). Four additional effective boundary
counterexamples are retained in boundaries-red.txt.
Further effective counterexamples are retained in language-red.txt,
claim-feedback-red.txt, dependency-usage-red.txt and route-red.txt.
The independent final stream review reproduced three additional failures. Six
business counterexamples are retained in stream-boundaries-red.txt; the later
stream-order-red.txt includes two further behavior failures plus three missing
accepted-marker assertions. provider-completion-red.txt and
remote-missing-id-cancel-red.txt preserve effective completion/cancel counterexamples.

`services/orchestrator/.venv/Scripts/python.exe docs/acceptance/D014/verify.py`
replayed 12 actual service workflows and retained three repair/retry histories
with exit 0. workflow-traces.json/repair-evidence.json include UTC time, Python/OS,
source hashes, actual task/step/check/artifact rows, checkpoints, usage events and
write-lease snapshots. Real model calls: zero. Only FakeProvider substitutes
scripted external responses; state transitions, blobs, artifact activation,
checks, A decision binding, lease handoff and budget logic are real modules.
Mechanical fixture checks parse actual immutable UTF-8 candidate bytes with the
Python AST parser, rather than accepting a canned validation result. Their
contract criterion explicitly names that mechanical condition. Semantic A
judgments remain explicitly fake external response fixtures in this evidence.

The workflow consumes an already-persisted RECEIVED attempt and validates its
contract/frozen route and immutable source hashes. Source content enters a
labelled untrusted-material package; it cannot change role, budget or write
permissions. B requests and actual provider events are recorded as steps/internal
outbox events. B completion does not establish PASS. Each candidate is staged as
an immutable blob/artifact_revision and activated in the D016 graph before checks.
Candidate language comes from allowlisted adapter metadata and defaults to und.
Contract dependencies bind exact current revisions from the same task/attempt,
including stored byte hashes, ArtifactDependency rows and graph upstream edges.
Upstream replacement invalidates the answer through the real D016 graph.

Initialization atomically pins the contract digest and claims a durable run lease.
Two Workflow instances cannot overwrite each other's checkpoint; the competitor
receives WORKFLOW_BUSY. A completed request rejects a changed contract without
starting a provider or changing its old approval/checkpoint. Before any A prompt
is written, every live profile route field must exactly match the frozen route;
same-family provider/model/adapter/connection changes cannot silently reroute A.

The actual provider family is checked per invocation before prompt creation.
A GPT contract cannot start B Claude on original Chinese context. Each accepted
provider.started event is persisted before reading the next event, with actual
request/execution/profile/step IDs in the task's current map and matching step
checkpoint. The immutable local invocation/usage ID is retained independently;
the first task request column does not replace the authoritative current map.
Accepted requests without usable remote IDs are still durable unknown executions.
Recovery consumes the current map's provider/IDs rather than the frozen A route.

Observed ConnectionError after acceptance, an unfinished stream, provider.error,
or a started event after completion blocks UNKNOWN_REMOTE and never creates a
replacement request. Both model.completed and supported provider.completed are
recognized, while mechanical/A review gates still determine output eligibility.
Successful B→A accepted fixtures preserve the current A reference and total 33.
FAILED/PUBLISHED stops all new requests/retries and preserves the terminal state.
Actual API cancellation and cancellation-flag observation retain pending remote
status even when an accepted execution has no IDs; no stop confirmation is invented.
Nineteen new boundary/control cases verify these paths. Real CLI workflow scope
remains blocked, so these observations do not certify real-provider execution.
`verify-stream.py` additionally replays six actual API/SQLite stream scenarios
and saves stream-evidence.json with real task/step/check/blob/usage rows, actual
current remote references and source hashes. Synthetic external events stand in
for the provider; no internal state, approval or budget result is substituted.

C mechanical observations produce actual version/hash-bound evidence files and
checks. A receives source content, candidate bytes/location, prior defects,
version history and acceptance mapping. A's four decisions enter separate
OUTPUT_PREPARING, REPAIRING, NEEDS_INPUT and BLOCKED paths. PASS is re-evaluated
through D013 against actual evidence. An A claim cannot overwrite a failed C
check, rebind an old revision, or turn B-only bytes into an A canonical document.
A.review checks bind the current revision and persist the complete contract,
decision and service-owned evidence root for NativePublisher.

Each quality repair produces a new immutable version and repeats C/A checks.
Defect persistence is measured by the unresolved defect IDs, even when the
entire report bytes change. Two unchanged-defect rounds or three autonomous B
repairs escalate to bounded A takeover. Before takeover, the actual b lease is
handed B→A, a snapshot of previous bytes is saved, and the lease is explicitly
returned A→B. Before/during/after epochs are retained. A failed takeover cannot
start an unbounded second takeover. Quality, connection and translation retry
counts are separate and never reset each other's cost/history; translation
execution itself belongs to part two and is not implemented here.

D015 budget checks run before every model start with a required explicit estimate.
The A reserve is protected. Missing budget/estimate, unknown usage and exhaustion
block. Actual reported fixture usage, including failed and cancelled requests,
is recorded with source/status; absent usage remains unknown rather than zero.
Before each external start, an unknown running request is durable in pending mode.
The first observed request_total/cumulative/delta report resolves that placeholder;
the real fixture's final reported total remains 33, without counting the placeholder.
Unconfirmed startup or interrupted responses retain unknown accounting rather than
implying that the request was billed zero or actually started.
Cancellation during a response prevents late candidate activation and any A
start. Repeated run calls retain prior history without restarting a provider.
Boundary failures save a stopped checkpoint instead of implying delivery.
The stop transaction also persists one deduplicated input.required or request.failed
event. The actual API history projects a fixed Chinese clarification/error and
does not reveal private A issues, model stages or raw exception strings.

The current supported workflow handles one UTF-8 candidate deliverable. Multiple
deliverables and binary-source preparation fail closed pending their dedicated
ports. Arbitrary same-user CLI executors lacking verified scope enforcement are
blocked. Claude requires missing full language/canonical/translation/publication
gates and remains explicitly BLOCKED, including under a fake adapter; no
part-two translator or formal publication provenance is claimed. Native GPT
success stops at OUTPUT_PREPARING; the workflow never calls publish or writes a
public answer event. All 12 traces contain zero answer.published events.

No installs, shared schema changes or commits were made.
