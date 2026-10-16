# Independent scenario-archive review

Date: 2026-10-15. Read-only review of the frozen correction in `tests/support/scenario_driver.py` and `tests/acceptance/test_scenario_driver.py`. The root reports final-v3 running with verification-source SHA-256 `be235c533d31cb6f4d79585d028c8da25cedd8d109edd022d33aa00bebcebe95`; this report does not assert final-v3 completion.

The original defect was an archive manifest recording live SQLite WAL/SHM files or pre-checkpoint database hashes that changed when the CLI exited. Original failure evidence remains in `docs/acceptance/part-three/archive-manifest-red.json`.

Independent checks actually executed against the correction:

| Command | Result | Checked behavior |
| --- | --- | --- |
| `services/orchestrator/.venv/Scripts/python.exe -m pytest tests/acceptance/test_scenario_driver.py -k 'checkpoints_all_sqlite_headers or refuses_busy_checkpoint or hardlink' -q` | 4 passed, 13 deselected, 1.04 s | Nested/multiple SQLite databases including lease stores and an unusual extension retain committed WAL rows; busy checkpoint fails closed; database and WAL hardlinks are rejected before writable checkpoint and external linked bytes remain unchanged. |
| `services/orchestrator/.venv/Scripts/python.exe -m pytest tests/acceptance/test_scenario_driver.py -k 'archive_manifest_is_valid and retention_glossary' -q` | 1 passed, 16 deselected, 1.53 s | Actual isolated CLI process exits before manifest validation; database quick checks and subsequent manifest validation pass. |

Both commands exited 0. These are five selected checks, not a full-suite result; deselection reflects the bounded review scope.

Static inspection confirmed that complete file discovery checks reparse paths and hardlinks before any writable SQLite connection. Actual SQLite headers identify databases independently of filename extensions. Each database receives a TRUNCATE checkpoint with explicit connection closure before manifest hashing. Busy/incomplete checkpoints and remaining nonempty WAL files reject the evidence run. Only WAL/SHM paths belonging to identified, checked databases are excluded; ordinary evidence such as `source-wal` remains included. SQLite main databases and lease databases remain in the manifest.

No remaining important finding was established in this bounded archive review. No product, test or script source was changed by this reviewer, and no tests were repeated solely to write this report. Root-owned final-v3 must still establish all-scenario post-exit manifest validity and complete regression results. This local review does not confer real-provider, human, signing or release qualification.
