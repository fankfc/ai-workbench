# Bounded Windows backup directory commit repair

2026-10-15. Scoped repair of the actual final-v3 failure: `create_backup()` reached its final pending-directory rename and raised `PermissionError`, Windows error 5. The failing test had not yet reached archive tampering, restore or live-tree comparison. Its `client` fixture supplies no backend factory and disables startup recovery, so it has no background task supervisor. Relevant SQLite/file connections use explicit closing. The identity of the actual process or handle responsible for that full-run failure remains unknown; an external scanner is a hypothesis, not an established cause. Existing final-v3 logs remain unchanged and failed.

## Actual mechanism probe

`windows-directory-commit-probe.py` uses `CreateFileW` without `FILE_SHARE_DELETE` on a file inside an owned disposable pending directory. The actual directory rename returns Windows error 5 while the handle is held. Closing the handle permits the same source-to-destination rename, with unchanged snapshot and live-data bytes. Three continuously held attempts all fail without changing either directory. An existing destination returns Windows error 183 and retains its bytes. `windows-directory-commit-probe.json` records zero open handles at the end and successful removal of only the owned fixture tree.

This establishes one deterministic Windows sharing mechanism matching the observed error, not the original failure's unknown owner.

## Repair and limits

`storage/directory_commit.py` owns a private commit helper used only at the final verified-directory rename in backup creation, archive import and restoration. It retries that same `Path.rename` operation only on Windows errors 5, 32 or 33, at most five attempts with four fixed delays totaling 0.30 seconds. It never retries snapshots, extraction, copying, model requests or publication, and never falls back to replace or move.

Before every attempt it checks the original absolute paths, strict `.pending-` plus 32 lowercase hexadecimal characters, identical parent directory, no symlink/reparse ancestor, unchanged source and parent `(device, inode)` identities, and an absent destination including dangling links. A target appearing or source directory being replaced between attempts stops the commit before another rename and preserves those paths.

Exhausted sharing candidates raise a dedicated `DirectoryCommitBusy`; uncertain ownership raises its non-busy `DirectoryCommitBlocked` base. All three callers preserve the pending directory for these outcomes instead of partially deleting it or masking the commit failure with a cleanup error. Other errors retain the existing failure cleanup. An inaccessible file can prevent safe deletion while an external handle remains held, so preserved pending directories are an intentional recoverable failure outcome; the API does not register them as successful backups. This helper provides local path/operation checks, not OS isolation against an arbitrary same-user adversary.

The API separately handles busy create/import/restore outcomes with fixed Chinese retry text, preserves original data, exposes no internal path/stack, and clears `storage_frozen` after a failed restore. Existing generic error handling remains for unrelated failures.

## Verification

The two actual Windows business regressions failed before the implementation (`backup-commit-red.log`): a released handle still caused creation to fail after its single rename attempt, and continuous occupancy was not bounded/recoverably retained. The new helper and API tests first passed 15 cases (`backup-commit-green.log`). After adding actual import/restore handle-release checks and a non-sharing failure cleanup case, the final associated run passed all **53** tests in 35.82 seconds (`backup-commit-final-green.log`), with only the existing Starlette/httpx deprecation warning. The final batch includes and supersedes the first green batch; counts must not be summed.

Coverage includes actual held/released and continuously held Windows handles; same source/destination retry; bounded errors; non-Windows and unrelated errors without retry; original-data and pending-byte preservation; owned cleanup on unrelated errors; target appearance; source replacement; invalid parent/name; reparse source; actual import/restore commit reuse; and all three API failures with no successful registration, frozen storage, or private-detail leak. All test-owned handles are closed in fixture cleanup.

Stable unparameterized mapping targets:

- `tests/storage/test_backup_commit.py::test_windows_commit_retries_same_owned_directory_after_handle_release`
- `tests/storage/test_backup_commit.py::test_windows_commit_busy_is_bounded_and_retains_owned_pending`
- `tests/storage/test_backup_commit.py::test_nonsharing_commit_failure_cleans_owned_staging_without_touching_live_data`

API cases are `test_backup_api_busy_preserves_data_and_never_registers_or_freezes[create-409]`, `[upload-422]`, and `[restore-409]` in the same file. Delivery owns independent review; root owns acceptance mapping and final full regression. This lane did not run a new full regression or modify historical logs, mappings, credentials or provider settings.

## Frozen source hashes

| File | SHA-256 |
| --- | --- |
| `services/orchestrator/app/storage/directory_commit.py` | `2540318D7C65BF886088F6CF32719CA75F6EFBBA84D8726DC5C12AC22F5CC28F` |
| `services/orchestrator/app/storage/backup.py` | `83DBD33D3EFDD6307EB7FC79047052BC726EE9E064F1D9714CAB8D6677DD12C7` |
| `services/orchestrator/app/storage/restore.py` | `9ACDBCE072310EADAB2AD0CFF8FF25126BB8672AF820B1D10A7A59EFB3062B73` |
| `services/orchestrator/app/api/backups.py` | `4D0B82FB7823F2F44E6206F321CE05B3BF45008B5A20C9DCEBD9CC6657FD330B` |
| `tests/storage/test_backup_commit.py` | `3E8D0B1B6363B0C30A0364AE41CD856DA32BB8A2BA4EA656F9E258883633346A` |
