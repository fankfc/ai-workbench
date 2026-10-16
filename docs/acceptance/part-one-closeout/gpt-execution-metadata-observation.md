# GPT execution metadata observation

One separately authorized continuation experiment completed on 2026-10-14. The official installed Codex app-server accepted one ephemeral thread and one `turn/start`, emitted a matching `turn/started` and `turn/completed` with status `completed`, and returned `{"count":3,"sum":6,"mean":2}` for the fixed inline sample `[1,2,3]`. This verifies that this bounded arithmetic turn actually completed. **The executed model identity remains unknown**, and production profile enablement and OS scope verification remain false. This observation does not qualify the original D020 production workflow or complete G1.

The new [continuation budget](continuation-budget.json) is separate from the old pilot's 3/3 submissions. Before launching, the observer atomically reserved one intent under a Windows file lock and replaced the budget file after flushing. It recorded `gpt_count=1` and `new_model_turn_submissions=1` out of a maximum of two. The final merge separately records one actual submitted/accepted/observed bound turn. There was one server launch, no retry, and no fallback to another route. The other permitted continuation submission belongs to root's ZCode lane.

The exact official executable and SHA were checked against D006's supported-entry manifest: Codex 0.160.0, SHA256 `4b01d5920e6785614727443bbecf343f4dedbb7347052b72ba805aab6353ef01`. The throwaway observer is `.tools/new-gpt-observer/observe.py`, SHA256 `c6dcef0490740f8376b9b0825a15c8f96d9c7b50f8a648f7864912433da0c21d`. It used the existing ProcessManager native Job launcher with a temporary stdin pipe; no production code or account/configuration/rule file was modified.

`initialize` enabled experimental API support. `thread/start` requested an ephemeral thread, `approvalPolicy=never`, read-only sandbox, no dynamic tools, and internal experimental raw events. Its returned policy matched `never/readOnly/networkAccess=false`. The single turn used low effort, a fixed JSON output schema, and an explicit read-only/no-network sandbox policy. This installed turn schema has no max-output-token parameter; the experiment instead enforced a shared 2,000,000-byte streaming output cap and a 120-second wall budget, reserving ten seconds for cleanup. It finished in **29.979 seconds**.

The prompt requested no tools, files, commands, delegation or network access. The observer would answer any server callback with honest error `-32601`, interrupt a known turn, and abort; it would also abort recognized tool-item notifications. It observed **zero server callbacks and zero recognized tool items**. These observations do not prove that built-in tools were disabled, that the full internal trace was available, or that the requested CLI sandbox was independently verified at the operating-system boundary.

## Response binding, usage and identity

The saved [sanitized observation](gpt-execution-metadata-observation.json) includes these actual service identifiers:

| Binding | Value |
| --- | --- |
| Thread | `01a1387e-dfb8-7072-9cc4-31fce3dbf629` |
| Turn | `01a1387e-e328-7f80-b908-9cf497b5678f` |
| Upstream response | `resp_05a3391d56e71f2a016acef9a8546c81919bc7ffb639ecc65e` |

One `rawResponse/completed` receipt carried all three identifiers and matched the owned thread/turn. Its usage equalled the final `thread/tokenUsage/updated.tokenUsage.total`: **25,044 input + 23 output = 25,067 total tokens**, with cached input, cache-write input and reasoning output all zero. The receipt and cumulative update describe the same usage; they must not be charged twice. Reasoning output is an output-token subset, not an additional amount. Currency cost and unreported provider-internal requests were not determined.

The requested and configured thread model was `gpt-6.1-sol`. The installed schema describes the thread model as configuration rather than per-turn execution telemetry. No `model/rerouted` notification appeared; its absence does not prove the executed model. The observer found no value for its whitelist of `model`, `modelId`, or `model_id` fields within the inspected raw-completion containers. There is consequently no candidate execution-model value to promote, and `actual_model_id=null` / `actual_model_identity_verified=false` remain accurate.

The experimental `RawResponseCompletedNotification` is explicitly internal-only. Its `usageMetadata.metadata` schema accepts arbitrary JSON rather than promising a model identifier. The observer searched named model fields through known containers (`usageMetadata`, `usage_metadata`, `metadata`, `response`, `msg`); it did not export arbitrary metadata keys or values. It recorded that the **usageMetadata wrapper was a dict**, but did not separately preserve the arbitrary metadata member's type. The JSON annotation now names this precisely as `usage_metadata_container_type` and marks `metadata_value_type=not_recorded`. These limits prevent a claim that no private or differently nested model telemetry could exist. A guessed value or a second experiment is not substituted for missing evidence.

Only the fixed arithmetic final text and its hash were persisted: SHA256 `74374201cf15a83f65cb169b3a80041ac8f5ef111b643268df7813c75b63837a`. The observer exported no raw stdout/stderr, reasoning, private prompt, credential, account record or unknown notification payload. Its bounded private buffers held 66,097 stdout bytes and 304 stderr bytes; they were not written to evidence files. Official runtime internal logging was not independently audited.

## Cleanup and scope

After the completed turn, the long-lived local app-server was closed under its owning Job. The local result is `cancelled`, `forced=true`, exit code 0. ProcessManager reports **zero running processes, active processes, owned handles and temporary directories**, with zero failed cleanups. That cleanup result does not establish a remote-stop confirmation: `local_cleanup.remote_state=unknown` and `remote_stop_confirmed=false` are retained alongside the separately observed completed turn.

All four owned native module/test hashes and the existing implementation-report hash still match `codex-protocol-implementation.json`. NativeRpc continues to reject generation methods. No production provider was registered or enabled, no new key was created, and no GUI or user settings were changed. The evidence establishes one completed native GPT turn with reported usage, while leaving execution-model identity and production runtime scope unverified.
