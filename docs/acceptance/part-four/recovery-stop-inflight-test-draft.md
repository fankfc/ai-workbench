# Pending stop-inflight regression draft

2026-10-15. Prepared during root's final-v1 source freeze. This document is a test/design draft only; production code and tests have not been edited for this third race and these proposed checks have not yet been run.

## Established race

The independent delivery reviewer observed: first launch owns a child waiting for its handshake; stop kills that child and reaches its second recovery-journal write; the write is deliberately held pending. The old launch's catch then reports offline. A second start checks only the mutable status and can start a new child before the first stop has finished. Releasing the journal lets stop resolve while the new child remains alive.

The generation checks fixed spawning after a previously pending mkdir. They do not represent the lifetime of the still-running stop operation, and the `stopping` boolean remains true after a completed stop because it also controls the child exit listener. Neither field is a suitable replacement for an owned in-flight stop promise.

## Minimal proposed repair

- Keep a private `stopTask?: Promise<void>` for the complete checkpoint, initial journal write, owned-tree termination and final journal write.
- `stop()` returns the existing promise when present. The first caller increments the launch generation and marks the visible state stopping before creating its private stop worker. Clear the promise only when that worker has settled.
- `start()` rejects while `stopTask` exists, independently of what an older launch has reported in the visible status.
- Preserve the existing cleanup-verification failures, journal-failure fallback, generation cancellation and post-stop retry behavior. Do not add a production delay or a longer timeout.

## Proposed negative tests

1. Pause only the second `desktop-recovery.json` write using the existing Vitest filesystem spy. The first spawned fixture is a local Node child with no handshake; later spawns use the existing healthy backend fixture. Wait until the child is owned, call stop, wait for its held journal write and the old start rejection, then attempt another start. It must reject while the stop is pending and the spawn count must remain one. Release the write, await stop, then a newly requested start must succeed. Always release the gate and terminate the fixture in test cleanup.
2. Start a healthy existing backend fixture, invoke stop twice concurrently, and count actual `/v1/checkpoint` requests and recovery-journal writes. Both callers must share one cleanup: one checkpoint and exactly the initial/final pair of journal writes. The owned child must be gone, and a later explicit start must still work.

Save the actual behavior RED separately from any mocking/setup error, then apply the minimal repair and run the desktop backend test file plus desktop typecheck. Delivery owns independent rereview; root owns final broader regression. Wait for root's explicit source-unfreeze message before editing production or test files.

## Execution after source unfreeze

Root subsequently authorized implementation. Both proposed behavior counterexamples actually failed before the repair: a second start resolved READY during the held stop, and concurrent stops issued two checkpoints. The minimal `stopTask` repair is now implemented; the old launch catch also preserves the active stop's visible state. `recovery-stop-inflight-red.log` records 2 failed, `recovery-stop-inflight-green.log` records all 13 desktop backend tests passed in 9.76 seconds, and `recovery-stop-inflight-typecheck.log` is empty because TypeScript completed with exit 0. No production timeout was added or increased. Delivery received the final source for independent rereview; root owns final regression and source freeze.
