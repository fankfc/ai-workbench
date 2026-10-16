"""Offline developer work-order CLI. No source-card command is executed implicitly."""
import argparse
import json
from pathlib import Path
import sys

from app.contracts.work_orders import (
    BlockedPayload, RepairPayload, create_handoff, create_report,
    draft_work_order, record_command, validate_handoff,
)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    sub = parser.add_subparsers(dest="action", required=True)
    draft = sub.add_parser("draft")
    draft.add_argument("--task-id", required=True)
    draft.add_argument("--contract-version", required=True)
    draft.add_argument("--allow", action="append", required=True, help="Exact caller-approved repository file; repeat as needed")
    draft.add_argument("--output", required=True, help="Fresh repository-relative directory")
    record = sub.add_parser("record")
    record.add_argument("--work-order", required=True)
    record.add_argument("--evidence", action="append", default=[])
    record.add_argument("--output", required=True)
    record.add_argument("--timeout", type=int, default=120)
    record.add_argument("argv", nargs=argparse.REMAINDER, help="-- executable arg1 arg2; shell=False")
    handoff = sub.add_parser("handoff")
    handoff.add_argument("--work-order", required=True)
    handoff.add_argument("--record", action="append", required=True)
    handoff.add_argument("--changed", action="append", default=[])
    handoff.add_argument("--unresolved", action="append", default=[])
    handoff.add_argument("--output", required=True)
    validate = sub.add_parser("validate")
    validate.add_argument("--work-order", required=True)
    validate.add_argument("--handoff", required=True)
    report = sub.add_parser("report")
    report.add_argument("kind", choices=["repair", "blocked"])
    report.add_argument("--work-order", required=True)
    report.add_argument("--payload", required=True, help="Repository-relative JSON payload")
    report.add_argument("--output", required=True)
    schema = sub.add_parser("report-schema")
    schema.add_argument("kind", choices=["repair", "blocked"])
    args = parser.parse_args(argv)
    try:
        if args.action == "draft":
            value = draft_work_order(args.root, args.task_id, args.contract_version, args.allow, args.output)
        elif args.action == "record":
            command = args.argv[1:] if args.argv[:1] == ["--"] else args.argv
            value = record_command(args.root, args.work_order, command, args.evidence, args.output, args.timeout)
        elif args.action == "handoff":
            value = create_handoff(args.root, args.work_order, args.record, args.changed, args.output, args.unresolved)
        elif args.action == "validate":
            value = validate_handoff(args.root, args.work_order, args.handoff)
        elif args.action == "report":
            from app.contracts.work_orders import _path, _root
            payload = json.loads(_path(_root(args.root), args.payload).read_text(encoding="utf-8-sig"))
            value = create_report(args.root, args.work_order, args.kind, payload, args.output)
        else:
            value = (RepairPayload if args.kind == "repair" else BlockedPayload).model_json_schema()
        print(json.dumps(value, ensure_ascii=False, indent=2))
        if args.action == "record" and value["exit_code"] != 0:
            return value["exit_code"] if isinstance(value["exit_code"], int) and 0 < value["exit_code"] < 256 else 1
        return 0
    except (ValueError, OSError, KeyError, TypeError) as error:
        print(json.dumps({"error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
