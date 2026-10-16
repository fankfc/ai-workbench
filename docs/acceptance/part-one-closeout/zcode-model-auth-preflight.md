# Public SDK model auth preflight

Fixed official commit `aac4755666d09fdcd70272fcf063c077a639015f`, narrow Node public SDK bundle and locally pinned official Anthropic/AI dependencies. The 24 offline business checks passed; external transport in those checks is a fixture.

The first real auth-only Node process exited 0, but the Python receipt decoder used an unsupported encoding alias and lost its private stdout; its receipt is unknown. Its original bytes/claim are archived in `.tools/zcode-model-observer/auth-first-receipt-lost`. It made no HTTP or model request. Three decoder business cases were red, then green using `utf-8-sig`.

A separately authorized second auth-only process returned the actual official AccountProviderRequestAuthService result: API material present, one key, existing device MID present, genuine original AI functions wired, and GLM-5.3 model factory created without inference. HTTP 0, model 0, headers applied false, SDK mutations 0, process exit 0, and all local resources 0. This is readiness evidence, not executed model identity or current availability. The earlier HTTP200 receipt was used only as a historical catalog.

Actual receipt: `.tools/zcode-model-observer/auth-second-result.json`. Its 22 source pins match after execution and exact public source bytes plus claim/receipt are sealed in `auth-second-sealed`; no credential/device/header/body values are archived. The read-only JS guard covers the reviewed trusted SDK call path, not an OS sandbox. Production and OS scope remain false.
