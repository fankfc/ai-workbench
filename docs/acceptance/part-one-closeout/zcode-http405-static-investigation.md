# ZCode HTTP 405 static investigation

The HTTP 405 root cause remains **unknown**. The sealed B-model-v1 receipt proves one actual official balance GET returned 200 and one SDK model POST returned 405. It does not retain the response body, `Allow` header, or a successful server model/id/usage. Static source cannot determine whether the response came from method routing, a distribution-specific control path, or another gateway decision. The investigation made no new HTTP, credential/auth-service, model, or installed-CLI call.

This report uses public source commit `aac4755666d09fdcd70272fcf063c077a639015f` and installed `D:/zcode/resources/glm/zcode.cjs`, SHA256 `b816e38656e70fb585fe2ab1ea010da89cda928dac1ccb5d83255fd18796da6e`. Installed line references refer to that exact file. No protected signing/proof algorithm was reconstructed or replaced.

## Confirmed request construction

The builtin Start Plan API uses `anthropic-messages` and base `https://zcode.z.ai/api/v1/zcode-plan/anthropic`. Public `model-execution.ts:383` maps this format to the Anthropic provider; `:328` uses `createAnthropic`; `:448` appends `/v1` unless already present. The Anthropic client then appends `/messages`. The observed request URL therefore agrees with the official adapter contract:

`https://zcode.z.ai/api/v1/zcode-plan/anthropic/v1/messages`

Removing `/v1`, changing POST to GET, or guessing another endpoint has no supporting evidence. The sealed transport already verifies matching genuine private auth, truthful external source headers, and `redirect: "error"`.

Public `AccountProviderRequestAuthService.ts:83` resolves Start Plan auth as the existing `zcodeJwtToken` returned privately as `apiKey`. `model-execution.ts:407` applies the per-attempt material; `:425` supports Anthropic `x-api-key` plus Bearer authorization. The B1 helper delegates through these official functions. This proves auth shape and application, not server acceptance or security-verification equivalence.

## Distribution and factory differences

| Boundary | Public source / B1 helper | Installed distribution | Implication |
| --- | --- | --- | --- |
| Request-security factory | Public `adapters/src/model/request-security-edition/index.ts` returns the original transport and no observations | Native `OfficialRequestSecurity` factory is present at line 2138 | B1 public-source execution is not distribution-equivalent; causation of 405 is unverified |
| Endpoint-routing factory | Bootstrap normally injects a routing port; B1 helper omits it. Public edition delegates to `createStaticProviderEndpointRoutingPort` | Native factory `Uhn` at line 2177 creates the dynamic resolver using `/api/v1/agent/configs` | Native runtime can consume a supported control-plane route; no current mapping was fetched here |
| Public static routing | Only the exact Individual Plan `api.z.ai/api/anthropic/v1/messages` and `open.bigmodel.cn/api/anthropic/v1/messages` endpoints are rewritten | Native dynamic mapping is server-controlled | Adding the public factory does **not** rewrite this Start Plan URL and is not a justified 405 fix |
| Start Plan verification policy | Public `shared/src/request-security-edition/verification-policy.ts` returns false, filters verification headers to `{}`, and sets interaction availability false | Native policy `EZi` at line 75 returns true for `access.mode === "start-plan"` | Public account auth material alone does not establish the native Start Plan verification bridge |

The upstream endpoint-routing spec explicitly preserves a common public contract while allowing edition replacement. `bootstrap/src/model-factory.ts:25` owns the process security state; `app/create-app.ts:564` wires the endpoint port into the real default model adapter. A supported native entry can preserve those installed defaults. Importing or replacing protected internal signing code is unnecessary and outside this investigation.

## Supported zero-tool native entries

The installed stdio `app-server` accepts supported `session/create` with `toolAllowlist: []`. Public protocol schema `shared/src/zcode-protocol/index.ts:1910` and installed schema at line 75 both allow an empty array. The native server passes it unchanged at line 15452. Native built-in registrar `Ise` at line 14460 and MCP registrar `$bt` at line 14478 create an empty Set, then exclude every candidate. Public registrars at `core/src/tool/handlers/index.ts:208` and `core/src/mcp/index.ts:76` agree. This is an actual supported way to expose zero model tools for a main session; omitting the allowlist has different semantics.

There is also the narrower supported `workspace/generateText` RPC. Its schema at `shared/src/zcode-protocol/index.ts:2443` accepts explicit `tools: []`, prompt/messages, a real model selection, truthful `querySource`, and output-token cap. `server-operations.ts:2773` forwards those values; `core/src/runtime/methods/workspace-generate-text.ts:164` uses `input.tools ?? []` and calls `model.generateText`. That text request does not execute a tool loop. The official host service `zcodeAgentService.ts:5074` first synchronizes the genuine account-provider overlay and supports cancellation through `workspace/cancelGenerateText`.

The request-auth dispatcher is also public: native `createProviderRuntimeHeadersPort` at line 15449 requests `interaction/requestProviderRuntimeHeaders`; public `provider-runtime-headers.ts:20` carries the same contract. Host `zcodeAgentService.ts:1386` resolves actual `AccountProviderRequestAuthService` material. A successful response must contain real `requestAuth` with `headersApplied: true`; failure must be reported honestly. Registry state and auth must come from their official owners, as in the previous metadata/auth evidence, rather than menu labels or synthetic eligibility.

The current public SDK dispatcher cannot establish the installed Start Plan verification path. The official host automatically replies only when verification is not required (`zcodeAgentService.ts:2535`); otherwise the genuine verification interaction participates. Its public edition is unavailable and discards verification headers. Returning actual OAuth-derived auth is supported, but declaring complete verification from that result alone is unsupported. A genuine distribution-compatible host bridge remains necessary before qualifying a native Start Plan model result.

## Limits of the alternative entry

- `toolAllowlist: []` constrains model-visible registrations. `mcpServers: []` does not disable MCP startup: `protocol-mcp-config.ts:6` returns undefined for it, while `app/runtime-config.ts:94` merges configured, plugin, and built-in servers. Hooks also remain a separate startup boundary at `:162`. Zero model tools is not OS scope enforcement or zero startup side effects.
- Native `workspace/generateText` uses `createRuntimeModel(...scope: "workspace")` with the default runtime retry budget (`runtime-model.ts:68`). Its public RPC schema has no retry-budget or physical-send-count override. It cannot inherit B1's single POST guarantee from a one-request client budget.
- The RPC response `selection` is reconstructed from `requestedSelection` (`workspace-generate-text.ts:260`), rather than raw server response model/id. It returns usage and finish reason but does not independently prove raw server model identity. The offline fixture deliberately returns a distinct server model and confirms that it is absent from the public result.
- The public zero-tool native entries are therefore concrete candidates for a separately bounded, genuine-host investigation. They are not a verified HTTP 405 repair and cannot by themselves close strict B1 identity, single-send, or OS-scope acceptance.

No new online helper was created. The actionable next route is the installed supported native entry together with a genuine official host account/verification dispatcher, preserving its edition factories and using a new reviewed budget and observation contract. If that genuine host bridge is unavailable, the supported boundary remains explicit; guessed URLs, synthesized verification, and private IPC are not substitutes.

## Bounded final check of public observation and host delegation

The official `session/debug` API is a read-only memory projection of `ModelNetworkStatus` events (`bootstrap/src/zcode-protocol/session-debug.ts:52`). It reports bounded network statuses, redacted headers, request ids, and usage. Its model field comes from the adapter's resolved request model (`adapters/src/model/runner-status.ts:78`); it does not expose a raw response body or distinguish a server-returned model/id. `workspace/generateText` also lacks that distinction.

ModelIO source has response `modelId`, `responseId`, and normalized usage (`runner-debug.ts:131`). These are AI SDK result metadata, not an independent raw-body proof: the pinned `ai/dist/index.mjs:4420` generates a missing response id and `:4422` falls back to the requested `stepModel.modelId`. Production ModelIO explicitly deletes `response.body` (`runner-debug.ts:639`). The public `workspace/updateModelIoPreferences` only controls global `fullRetentionEnabled`; it has no per-request safe-field selector and no model retry override. Reading or exporting whole debug context would exceed this task's observation boundary, and was not done. These sources establish a possible future supported diagnostics input, while leaving strict raw server identity unverified.

The public UI edition is also incomplete for this delegation. `packages/ui/src/request-security-edition/index.ts` provides inert interaction components, `claim.ts` returns an empty `{}` with no genuine verification material, and shared `verification-policy.ts` declares the interaction unavailable. The native host callback contract exists, but this workspace has no exposed supported way to attach its own stdio request to the installed genuine Host/Renderer verification responder. Direct private IPC, proof/signature reconstruction, and replayed verification material were not attempted.

The current integration status is **`blocked_supported_host_integration_required`**. Its smallest environment dependency is an official distribution-compatible Host/Renderer, already logged into the user's Start Plan, that exposes a supported delegation of account auth and genuine verification to this owned native runtime. A separately reviewed native observation/budget contract must then establish raw server identity and physical-send bounds. Starting another public SDK helper or changing the URL cannot supply those dependencies.

## Offline verification

`node .tools/zcode-405-investigation/source-business-checks.mjs` passed **9** checks. It executes actual public source functions in a fixture VM for URL normalization, static routing, built-in/MCP filtering, empty MCP conversion, and workspace text delegation; it checks exact installed schema/registrar/policy evidence without starting that CLI. Network/model/auth calls and installed CLI starts were zero. All **31** original B1 source pins still matched.

The source digests and check receipt are saved in `.tools/zcode-405-investigation/source-business-checks.json`. Existing B1 source, bundle, claims, receipts, budget, and seal were preserved. `http405_root_cause_verified`, `model_identity_verified`, and `production_enabled` remain false.
