# Independent work-order review

Scope: `services/orchestrator/app/contracts/work_orders.py`, `scripts/work_order.py`, `tests/contracts/test_work_orders.py`, and `docs/runbooks/work-orders.md`, against execution manual sections 1, 2, 9 and 10. The reviewer authored role prompt integration and did not author these work-order files. This is a bounded independent source and adversarial probe review, not a two-lane merge approval; all four team slots were occupied, so the code-review skill's two additional delegated reviewer lanes were unavailable.

## Material finding

**MEDIUM — Windows case aliases bypass protected and unique file scope checks.** Before correction, `_scopes` (`work_orders.py:185`) compared normalized strings with case-sensitive `set` membership and exact string/prefix comparisons. On this case-insensitive Windows host, `BOARD_REF.upper()`, `KEY_REF.upper()`, and both `src/allowed.py` plus `SRC/ALLOWED.PY` were accepted. These aliases identify protected or duplicate filesystem paths. The additional uppercased plan `data/tasks-02.json` path has the same prefix-comparison problem. This violates the function's explicit protected-file exclusions and unique exact file list semantics. It does not establish an OS sandbox escape; the same-user/no-sandbox limitation is already correctly documented.

Actual initial probe output is preserved in `work-order-review-probes.txt`. The finding was sent to the parent and implementation owner before any code changes. The requested correction is to compare filesystem identity using the host's path semantics for exclusions, duplicate checks and changed/repair scope membership; retain the original display paths where useful. The implementation owner is adding tests before correcting the code. Retest status will be appended below.

## Source observations

- `draft_work_order` selects the exact unique board and data task cards, preserves the complete selected guide section and raw card data, and includes only direct dependency artifact references/hashes. It does not expand the dependency's own `requires` list or copy prior handoff history. Draft creation writes only a fresh output and local integrity key, not the task board.
- `_order` authenticates saved work orders and rechecks selected task card/guide section and direct dependency card bindings. Task material's command strings remain data. `_argv` accepts explicit argument arrays, blocks implicit Windows batch scripts, and `record_command` uses `shell=False` with streamed output, bounded timeout and actual return code.
- Command records bind task, contract version, complete work-order byte hash, caller argv, process log/hash, evidence bytes and tested revision. `_records`, `_changed` and `validate_handoff` recheck these bindings and reject nonzero/timeout outcomes, missing or changed evidence, forged local records and stale revision data. Local acceptance retains `review_required` and `task_completion_changed: false`; it makes no real-provider or complete-task claim.
- Repair/blocked payloads retain defect/requirement/locations, failure/direct evidence, allowed files, pass conditions/rerun argv, attempted actions, external conditions and independent work as applicable. `create_report` adds retrievable evidence hashes and measured current revision/hash. Human `artifact_version` remains a label; actual current bytes are measured separately.
- `_relative`, `_path`, `_reject_reparse` and file link-count checks cover traversal, absolute/drive/stream paths, device names, reparse points and hardlinked files. Directory artifacts hash a recursively checked file index rather than copying unrelated contents. These are gateway checks and local record integrity, as documented; they do not monitor arbitrary same-user processes.
- CLI `record` returns the actual process failure when representable, otherwise nonzero for timeout/launch errors. Validation and malformed payload failures return nonzero JSON errors. Explicit shell argv remains caller authorization, not an instruction sourced from a task card.

The review did not repeat all existing behavior tests solely to increase counts. No other material issue was identified in the reviewed source. Final confidence remains bounded to local source/records, not adversarial same-user secret protection, OS isolation, semantic test sufficiency, or real-provider acceptance.

## Retest and closure

The owner corrected filesystem identity comparisons using `_identity` (`work_orders.py:99`), which applies resolved host path identity and `normcase`. Protected scopes, duplicate scopes, changed-file membership, repair subsets and duplicate command-record references now share that identity check. Original display paths and trusted argv are preserved. The owner added seven failing Windows cases before the correction and reports all 39 work-order tests green in `work-order-tests/windows-identity-green.log`; that owner test count is not represented as an independent rerun here.

The independent reviewer reran the original probe after the correction, adding the uppercased plan-data path. All four cases were rejected with the expected protected-file/duplicate errors, and the actual process exited 0. See `work-order-review-probes-fixed.txt`; the original accepted results remain in `work-order-review-probes.txt`. Source reinspection found the shared comparison applied at each affected boundary. The material finding is **resolved**. No unresolved material finding remains in this bounded review; the unavailable additional merge-approval lanes and the documented local/no-sandbox limits remain outside this conclusion.

Reviewed final SHA-256:

- `services/orchestrator/app/contracts/work_orders.py`: `b46ee6114443269b982d32d72f7596d96b951f9f40254f3bd8e8c7add53037a0`
- `scripts/work_order.py`: `a2adc699bfb3643156ce57c37cec1ca4e64eb4b897111e7e5b7a23a0a7bd5732`
- `tests/contracts/test_work_orders.py`: `de92e2db5642a18fb1434858499928255a2b85a8e8523aed3dcce794a0b86b40`
- `docs/runbooks/work-orders.md`: `b51ce2e55133d383a8a2e86d0585e42ba3afdc366fcb84f9f67cae7e74632e8b`
