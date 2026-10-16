# D004 desktop/CLI matrix

| Capability | Evidence/status |
| --- | --- |
| Native CLI | Version 2.1.296; supported help observed |
| Desktop sees CLI session | unknown; no GUI/account inspection |
| Same desktop/CLI session | unknown |
| Same desktop/CLI login | unknown |
| Same desktop/CLI quota | unknown; token usage and quota are separate |
| Actual model identity | unknown |
| Resume after interruption | unverified; disabled |
| Cancellation and remote stop | unverified; disabled; local processes exited |
| Different workspace/context isolation | Unique directory per start; two successful task comparison unverified |
| Production execution | disabled: AUTHENTICATION_REQUIRED |

Credential stores were accessed only by the official CLI. No plaintext credentials or account configuration were read by the probe.

