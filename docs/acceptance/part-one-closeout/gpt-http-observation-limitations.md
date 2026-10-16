# Prior INFO observation limitation

The completed HTTP observation in `gpt-http-identity-observation.json` queried only the owned thread and execution window. Its read-only query succeeded and returned zero matching positive model INFO/WARN rows. This means **not observed**, and does not establish absence of a server model header or native event.

The helper waited at most two seconds after completion, while the official `rust-v0.160.0` native SQLite log writer uses a ten-second batch flush interval. No additional model execution or broader account-log scan is justified by the zero-row result. The original JSON and Markdown hashes remain preserved; this annotation records the limitation without rewriting historical evidence.

The later independently authorized SSE observation uses a distinct, source-supported pre-normalization response-field port and a separate maximum-one-submission budget. It cannot qualify production identity, tool isolation, or the original runtime route.
