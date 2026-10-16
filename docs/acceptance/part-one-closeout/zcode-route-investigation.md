# ZCode supported-route investigation

The installed CLI has two different supported execution modes. A standalone `app-server` expects the desktop host to supply the account registry and authorization callbacks; ordinary `--prompt` initializes its own official credential-backed registry, but that implementation only supports Individual Coding Plan account providers. The existing GUI Start Plan cannot become that account type by changing a model selection.

This investigation read only installed public runtime/resources, project probe scripts and redacted metadata evidence. It did not start ZCode, call a model, modify account configuration, or read credential bytes. One `Test-Path` check confirmed that the default shared credential file exists; existence is not authentication or plan verification. Source: `D:/zcode/resources/glm/zcode.cjs`, CLI 0.16.9, SHA256 `b816e38656e70fb585fe2ab1ea010da89cda928dac1ccb5d83255fd18796da6e`. Line references below belong to that exact installed file.

## The callback timeout and the next empty catalog

`QZ` at line 15440 defines ZCode `timedOut=-32022`. The bundled MCP dependency also uses the same number for a different error; that is not the ZCode session/create path. `session/create → dci → jFn → hhc → Xai` at lines 15449/15452 first sends this server-to-client request, with a 15-second deadline (`att=15e3`, line 75):

```json
{"id":"server-1","method":"session/requestRuntimePreferences","params":{"sessionId":"<created-session-id>","scope":"runtime-materialization"}}
```

The earlier `.tools/auth/zcode_model_catalog.py` call loop discarded every message whose id did not equal the requested integer. It therefore ignored this callback. Its [saved result](../desktop-connect-20261013/zcode-model-catalog.json) records create failure `-32022` and zero model turns. This establishes a strongly supported timeout cause; the old summary did not retain the full error message.

An unsupported client capability must be answered honestly, using its actual server request id:

```json
{"id":"server-1","error":{"code":-32601,"message":"Client does not implement session/requestRuntimePreferences"}}
```

`Xai` explicitly applies the official compatibility fallback for `-32601` or `-32020`: memory disabled, context strategy `preflight-v1`, native search enabled and AskUserQuestion auto-resolution enabled. Timeout does not invoke that fallback. For a metadata-only session with no tools and no prompt, this is a supported capability response, not an invented user setting. Root's [corrected actual zero-model probe](zcode-metadata-fixed.json) confirms create success, one honestly rejected runtime-preferences callback, no headers callback, and an empty available-model array.

The empty catalog is a separate, directly supported cause. `hdi` at line 15459 calls `xCt(env)` with no standalone option. `xCt` at line 15438 uses `MutableAccountProviderConfigSource` (`Vte`), whose initial snapshot has empty providers. Only its `standalone` branch creates the official credential store and `AccountProviderService`. The desktop public host code in `app.asar/out/host/index.js` has `syncAccountProviderConfigToClient`: it reads its genuine account-service snapshot, sends `provider/updateAccountConfig`, and checks the acknowledged revision. The corrected independent server has not received that host snapshot. Merely pointing at a bundled model-definition file does not supply it.

Do not synthesize `entitled`, account state, or a supposed GUI snapshot from menu labels. The official provider-headers callback is also different: `interaction/requestProviderRuntimeHeaders` expects a genuine supported host authorization result. Its success schema requires `headersApplied:true` plus `requestAuth`; it has no runtime-preferences fallback. A missing implementation should return method-not-found or an honest `headersApplied:false` result, never claimed success. Permission/browser/other unimplemented callbacks must also fail closed. Request/response envelopes at line 75 are strict `{id,method,params?,trace?}` / `{id,result}` / `{id,error}` without a `jsonrpc` field.

## Ordinary print mode and a non-secret configuration overlay

`V4n/runPrompt` at line 15544 calls the provider registry with `standalone:{...}` and passes the resulting internal `providerRuntimeHeadersPort`. `NNn` and `Toi` at line 15438 enumerate only `zhipu-account` providers whose access mode is `individual-coding-plan`; `Coi.refreshBeforeModelRequest` rejects other account modes. The shipped account IDs include `account:zai-individual-coding-plan`, `account:bigmodel-individual-coding-plan`, and the separate Start Plan IDs `account:zai-start-plan`, `account:bigmodel-start-plan`. Root observed and exercised the existing GUI Start Plan; that observation does not establish the separate Individual Coding Plan prerequisite. Neither login nor a default-model pointer supplies a missing plan.

The official shared credential-store resolver `Vta` at line 2201 resolves `<ZCODE_DATA_BASE_DIR or home>/.zcode/v2/credentials.json`. The default file `C:/Users/asd15/.zcode/v2/credentials.json` exists. Its content was not read, copied or decrypted. `gDe` is a built-in refresh reporter, not the credential-store resolver. `doctor --json` at line 15610 reports installation/runtime metadata; it is not an authentication-status command.

The runtime supports a new, workspace-owned **non-secret** personal-config file through `ZCODE_PERSONAL_PROVIDER_CONFIG_FILE` (path resolver `mfs`, line 91). Keep the user's data-base directory and credential store untouched. The schema/encoder at line 72 accepts this minimal shape:

```json
{
  "schemaVersion": 1,
  "config": {
    "providerConfigRules": {"providerRules": []},
    "modelConfigRules": {"providerModelRules": [], "manualProviderModelRules": []},
    "providerOrder": [],
    "defaultModelSelection": {
      "providerId": "<official-runtime-verified-available-provider>",
      "modelId": "<exact-model-id>",
      "options": {"reasoningLevel": "<supported-level>"}
    }
  }
}
```

No overlay file was created or executed by this investigation. Such a file only selects an already eligible model; it must not add account access, an `entitled` claim, API keys or credentials. The shipped most-specific GLM-5.3 model rule declares `low/high/max` reasoning values, rather than the generic `disabled/enabled` rule. A live registry's effective model options remain authoritative. The CLI strict argument parser has no `--model`, `--provider`, `--default-model` or `--rpc` option. Interactive `/model` saves a default, but `--prompt '/model …'` does not take the same command-center path and can start a model turn; it is not a zero-model configuration command.

## Existing GUI sessions and the smallest next checks

`session/list` (line 15449) can list persisted session metadata without materializing a model or reading raw credential/configuration files. With an already known fixed-workspace path:

```json
{"id":10,"method":"session/list","params":{"workspace":{"workspacePath":"<fixed-GUI-sample-directory>","workspaceKey":"<same-directory>"},"limit":10}}
```

For persisted-only rows, its `CUe` projection does not provide model selection unless the session is resident in that same protocol server. `session/read` also requires a resident session; it is not a direct persisted-history lookup. `session/resume` materializes the persisted session and uses the runtime-preferences callback above. `NYo` at line 14822 reads the latest `runtime/model_selection` session entry; `restorePersistedModelSelection` at line 15438 restores provider/model/options only after registry validation. An unavailable provider leaves the runtime selection unbound; it does not silently convert Start Plan to an Individual plan. CLI `--resume <id> --prompt <task>` uses this same persisted-selection restoration before the new turn. Merely sharing a data-base home does not prove the same configured session database; the public CLI default is `~/.zcode/cli/db/db.sqlite`, and `vae` resolves the actual configured path.

The smallest currently justified route is: retain the GUI's completed fixed-sample evidence; finish zero-model protocol diagnostics with honest callback responses; record the host-only empty-registry reason; use ordinary print mode only if the official standalone account service independently establishes an already eligible Individual plan, with a new non-secret selection overlay and a fresh bounded model-turn allowance. Existing Start Plan automation requires the genuine supported desktop-host registry/authorization bridge. A new login, guessed model name, global default, or unsupported headers response cannot replace that bridge. The [official CLI README](https://github.com/zai-org/ZCode/blob/main/apps/zcode-cli/README.md) establishes the Node bundle entry; the installed public runtime above establishes these version-specific protocol/account restrictions.

## Authorized implementation design

The new `zcode_protocol.py` will provide the metadata method policy and result projection over an injected bounded NDJSON client; `native_rpc.py` owns Windows process management. It will allow only capabilities/create/read/close for its own metadata session, answer unsupported callbacks honestly, forbid model-start and account-mutation methods before transport, and preserve unknown identity. An empty catalog yields `HOST_ACCOUNT_CONTEXT_REQUIRED`. Fixtures will test callback timeout repair, unsupported credentials/permissions/browser, malformed metadata, unexpected model calls and cleanup/error bounds. No fixture will qualify real connectivity or OS scope enforcement.
