# D005 ZCode adapter report entry

Status: **blocked**. Actual required connection reason: `MODEL_SELECTION_REQUIRED`. The official bundled CLI 0.16.9 reached a real session but failed before model creation with CONFIGURATION_ERROR (“Select a model before continuing”). Actual GLM identity, login, tool task, cancellation and resume remain unverified. Production and further bounded-probe registration remain disabled.

Implementation and verification: [combined report](../D004-D006-implementation-report.md), [capabilities](../zcode-capabilities.json), [profile](../profiles/zcode.json), [probe report](probe-report.json), [second actual attempt](real-discovery-2.json), [redacted structured failure](real-discovery-2.stdout.redacted.txt), [disabled gate check](gate-check.json), [supported entry/hash](supported-entry.json), [session matrix](session-matrix.md). No direct GLM API was substituted for ZCode.
