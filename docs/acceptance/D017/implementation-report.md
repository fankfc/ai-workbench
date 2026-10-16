# D017 implementation record

Status: implemented; 41 tests passed with exit 0. Model calls: 0.

The command `services/orchestrator/.venv/Scripts/python.exe -m pytest tests/integration/test_workspace.py tests/integration/test_context_gateway.py -q`
passed all 41 tests. `verify.py` additionally recorded 11 actual scope checks
and three persistent write-lease epochs in scope-matrix.json/isolation-report.json.
Both JSON records include UTC time, Python/OS, exact command and source hashes.

The original importable workspace stub produced a behavior failure in the first
standalone scope test. The remaining initial tests could not set up that stub;
those setup errors in red.txt are not counted as independent behavior evidence.
The final suite exercises actual filesystem operations and a real Windows
junction, not mocked path strings alone.

Each task/attempt has independent input/a/b/translation/evidence/artifacts areas.
Scope resolution rejects traversal, encoded traversal, drives, UNC, alternate
data streams, reserved names, cross-task absolute paths, hardlinks, symlinks and
Windows reparse points. Original bytes are immutable through ingestion and have
a checked SHA manifest plus Windows read-only attribute. B may write only b;
sources and evidence are available through trusted service operations.

Persistent write leases use an interprocess file lock and atomic metadata
replacement. A takeover issues a new token/epoch and immediately invalidates B's
old lease. A's decision area cannot be handed to B. Lease state survives reopen;
competing owners cannot acquire a simultaneous lease. Writes are atomic and
performed under the same lock as handoff.

Claude reads require a service-registered, immutable English-view record with
matching source/view hashes, validation ID, language/status, and explicit QA
flags. The gateway checks protected byte spans and rejects non-Latin natural
language outside those spans. GPT/GLM receive authorized original bytes. Unknown
family, missing proof, altered hashes, missing QA and changed formula/code bytes
all block. Source prompt injection remains untrusted material and cannot grant
tool or write permissions. This is a reference/integrity gate; it does not
implement or certify part-two translation quality.

Protected spans are validated and copied into immutable tuples at construction.
The gateway also copies its trusted registry records. Mutating a caller's original
span list or original proof object cannot expand the registered exemptions; two
regression tests reject unchanged Chinese text after those mutation attempts.

The acceptance runner proved the ordinary native CLI limitation: a harmless
same-user Python fixture started in b could write ../a/cli-bypass.txt inside its
disposable task. A working directory therefore is not an OS security sandbox.
External execution that requires enforced filesystem isolation is blocked by
default with OS_SANDBOX_UNVERIFIED. Supported use here is the service gateway;
the evidence explicitly records the CLI bypass instead of claiming unsupported
ACL/token enforcement. Filesystem replacement races by arbitrary external
same-user applications remain outside this service interface's enforcement.

No model calls, installation, shared schema changes or commits were made.
