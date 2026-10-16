# ZCode metadata protocol implementation plan and evidence

Authorized files: services/orchestrator/app/providers/zcode_protocol.py and tests/contracts/test_zcode_protocol.py. Shared native_rpc.py is owned by process_d011. Original adapters, workflow, scripts, accounts and locks are outside this change.

Design: an injected, bounded NativeRpcClient owns all process and NDJSON behavior. The ZCode client allows only capabilities, fixed zero-model create, and read/close of its own metadata session. It projects only public model references and fixed diagnostics; identity, account authorization and OS scope remain unverified. An empty catalog returns HOST_ACCOUNT_CONTEXT_REQUIRED.

- [x] Fixture tests for fixed requests, malformed metadata, forbidden calls, foreign sessions, timeout/output bounds and cleanup.
- [x] Separate scaffold failure and meaningful behavior RED.
- [x] Implement method policy and projection without another subprocess runner.
- [x] Verify owned contract tests, including actual local NDJSON fixtures through the common managed transport.
- [x] Record green output and hashes; root owns actual installed-provider metadata probes.

Implemented interface: ZCodeProtocolClient(command, cwd, client_factory=None, timeout_seconds=40, max_output_bytes=65536).probe() returns a whitelist-projected dict. The timeout maximum is 60 seconds for the whole probe; byte limits are 1024–2,000,000. NativeRpcClient owns process startup, bounded NDJSON, callback errors and cleanup. The consumer does not import subprocess or implement another process runner.

The default transport positively pins the canonical installed Node executable and ZCode CJS paths, exact app-server argv and their existing installation hashes before launch. Use ZCodeProtocolClient.fixed_command(cwd) for that argv. Trusted test/port injection is explicit; the result marks injected_transport and never calls that fixture an installed entry. This strengthened a concrete independent reviewer observation; two entry-policy tests were RED before the fix.

Every probe requests runtime/capabilities and exactly one guarded, deferred, title-disabled, empty-tool-allowlist metadata session. It allows read/close only for the session returned to that client. Prompt/target/resume/continue CLI flags and generation/account-mutation/model-selection methods are rejected before transport. The close response must contain closed=true, and the common transport must confirm cleanup and zero running processes, handles and temporary directories. Redacted identifiers are rejected rather than reused as different RPC handles. Unknown identity, false production enabling and false OS scope enforcement remain explicit even when a model directory exists.

Verification: **55 passed in 1.66 seconds**, [final owned log](zcode-protocol-green.log). This includes four actual Windows native Python fixture processes over the common Job/pipe client: an honestly unsupported runtime-preferences callback produces the expected empty catalog, while provider-headers, permission and browser callbacks receive unsupported responses and remain failed/unverified. These are local protocol fixtures with zero installed-provider/model calls. Callback transport tests supplement the common-client author's own RED/green cycle; they do not establish real ZCode authentication.

After final shared cancellation/activity/ownership repairs, process_d011 reran both connector consumers: **97 passed in 6.41 seconds**, [shared log](native-connectors-green.log). This includes the same 55 ZCode cases against the frozen common transport. The implementation JSON records that newer shared hash separately from the earlier owned run.

RED records: [missing-module scaffold](zcode-protocol-scaffold-red.log), [33 business failures](zcode-protocol-red.log), [close and sensitive-ID failures](zcode-protocol-close-red.log), [timeout bound](zcode-protocol-timeout-red.log), [output floor](zcode-protocol-output-floor-red.log), [positive entry pin](zcode-protocol-entry-red.log). The first successful four native-fixture run is preserved separately in [its log](zcode-protocol-native-fixture-first.log). Source hashes and the consumer interface snapshot are in [implementation evidence](zcode-protocol-implementation.json).

Supported-route evidence: [investigation](zcode-route-investigation.md), [root's actual zero-model result](zcode-metadata-fixed.json). The installed app-server still has no genuine desktop-host account context. The metadata client therefore retains HOST_ACCOUNT_CONTEXT_REQUIRED and does not turn the existing GUI Start Plan into a standalone Individual Coding Plan.
