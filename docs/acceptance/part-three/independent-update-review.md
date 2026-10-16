# Independent D053 update-coordinator review

Date: 2026-10-14. Scope: D053 plan, `apps/desktop/src/main/update-coordinator.ts`, preflight `updates.ts`, and `tests/release/update-coordinator.test.ts`. Independent read-only review with one isolated adversarial reproduction. No real installer, signing account, network model or distribution action was used.

## Confirmed finding

**P2 — Preserve committed transaction state if resuming tasks fails.** At the initially reviewed `update-coordinator.ts:153–158`, the coordinator persists COMMITTED and then awaits `ports.resume()`. If resume throws, the catch handler treats this terminal phase as a pre-install failure and calls `resumedReject`, replacing the journal with REJECTED. The actual candidate installation, migrated schema and authoritative version are already committed. The user receives a rejection message that incorrectly implies the previous version/data were retained. Terminal recovery also returns without retrying unfinished resume work.

Minimal reproduction: reuse the file-backed local fixture, wrap its private resume port so its first call throws `Error('resume failed')` and subsequent calls delegate to the fixture's original resume; execute update with its unchanged authenticated manifest and valid observations. The fixture uses harmless text bytes as package contents and JSON as schema data; this is coordinator evidence, not native installation evidence. Run by bundling a temporary copy of the fixture and coordinator with local esbuild, excluding the Vitest suite.

Observed process exit 0:

```json
{"state":"REJECTED","activeVersion":"1.1.0","schema":4,"sequence":11,"journal_phase":"REJECTED","actual_program":"signed candidate bytes","actual_schema":4,"resume_attempts":2}
```

Correction requested: persist unfinished resume separately, preserve terminal transaction state, prevent a new update while resume is pending, and recover by retrying resume rather than repeating rollback or changing COMMITTED into REJECTED. Also cover ROLLED_BACK and REJECTED terminal resume boundaries. Owner acknowledged and is implementing this correction; independent revalidation pending.

## Other reviewed boundaries and limits

Within the explicitly trusted private-port model, the coordinator binds canonical authenticated manifest bytes to staged package hashes, checks signature chain/publisher/timestamp observations, verifies a saved predecessor and schema-matching backup before installation, validates installer/migration/health receipts before authoritative commit, and bounds recovery attempts. Rollback rechecks predecessor and backup hashes and verifies the restored schema and health before committing the previous installation. Renderer code does not supply signature or installation authority.

Filesystem checks reject path escape, symlinks and hard-linked files; journal writes use a flushed temporary file and rename. The module's process-local root lock and pending journal fence were inspected; no claim of cross-process lock coverage or native power-loss durability is made. Real Windows signature adapters, native installer settlement, backup adapter integration and signed interruption drills remain external evidence gates. Trusted-port test receipts cannot substitute for them.

Recommendation at this review point: REQUEST CHANGES for the confirmed P2. No other important finding established within the bounded inspected scope. Full regression is owned by the root agent and was not rerun here.

## Independent revalidation of frozen correction

The owner added durable `resumePending` state and a terminal resume recovery path. Independently reran the exact first-resume-fails reproduction against the frozen correction, then instantiated a new coordinator and called `recover`. Explicit assertions passed (process exit 0):

```json
{"initial_state":"BLOCKED","initial_active_version":"1.1.0","initial_phase":"COMMITTED","initial_resume_pending":true,"recovered_state":"COMMITTED","final_phase":"COMMITTED","final_resume_pending":false,"recovery_calls":["resume"],"actual_program":"signed candidate bytes","actual_schema":4,"resume_attempts":2}
```

Also independently injected a failed candidate health check, allowed rollback to complete, and failed its first resume. A fresh coordinator recovered with only a resume call; explicit assertions passed (process exit 0):

```json
{"initial":"BLOCKED","phase":"ROLLED_BACK","pending":true,"recovered":"ROLLED_BACK","final_phase":"ROLLED_BACK","pending_after":false,"recovery_calls":["resume"],"active_version":"1.0.0","schema":3}
```

Both checks confirm that recovery does not repeat install, migration, rollback installation or backup restoration after the terminal transaction has completed. Read-only inspection additionally confirmed that pending resume prevents new updates and terminal recovery shares the persisted three-attempt recovery bound. The original P2 is **closed**. The earlier REQUEST CHANGES recommendation records the pre-fix state; no remaining important finding was established within this bounded review. Native external-install/signing limitations and root-owned full-regression responsibility remain unchanged.
