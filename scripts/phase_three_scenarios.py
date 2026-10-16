"""Persist one isolated execution of each registered local acceptance case."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
from uuid import uuid4

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'tests'))
from support.manifest import source_build_id, write_json

CASES = [
    ('D041', 'driver_contract', {}), ('D042', 'requirement_coverage', {}),
    ('D043', 'translation_corpus', {'case_id': 'en-zh-negation-number', 'candidate': '当差值小于 0.03 时允许发布。'}),
    ('D044', 'evaluation_protocol', {}), ('D045', 'usage_reconciliation', {'fault': 'cumulative_with_duplicate'}),
    ('D046', 'optimization_gate', {}), ('D047', 'security_boundary', {}), ('D048', 'fault_matrix', {}),
    ('D049', 'gui_evidence', {}), ('D050', 'local_performance', {'history_tasks': 10000, 'active_tasks': 1}),
    ('D051', 'backup_restore', {'fault': 'missing_chinese_artifact'}), ('D052', 'windows_install', {}),
    ('D053', 'signed_update', {'fault': 'invalid_publisher'}), ('D054', 'release_manifest', {}),
    ('D055', 'real_journey_audit', {}), ('D056', 'feedback_bundle', {'include_content': False}),
    ('D057', 'release_decision', {}), ('D058', 'retention_glossary', {}),
    ('D059', 'incident_rollback', {'fault': 'critical_translation_after_model_change'}), ('D060', 'final_handover', {})]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--case')
    parser.add_argument('--options', help='JSON options override for one selected case')
    args = parser.parse_args()
    if args.options and not args.case:
        parser.error('--options requires one --case')
    records = []
    build = source_build_id()
    for card, case, options in CASES:
        if args.case and args.case != case:
            continue
        if args.options:
            options = json.loads(args.options)
        run_root = REPO / 'artifacts/qa' / card / ('r' + uuid4().hex[:8])
        run_root.mkdir(parents=True)
        command = [sys.executable, 'tests/support/scenario_driver.py', case, '--root', str(run_root),
                   '--options', json.dumps(options, ensure_ascii=False)]
        observed = subprocess.run(command, cwd=REPO, capture_output=True, text=True,
                                  encoding='utf-8', errors='replace', timeout=120, check=False)
        (run_root / 'driver.stderr.log').write_text(observed.stderr, encoding='utf-8')
        result = json.loads(observed.stdout) if observed.returncode == 0 else None
        record = dict(card=card, case=case, command=command, exit_code=observed.returncode,
            time=datetime.now(timezone.utc).isoformat(), build_id=build,
            run_root=run_root.relative_to(REPO).as_posix(), result=result)
        write_json(REPO / 'artifacts/qa' / card / 'local-evidence.json', record)
        records.append(record)
        print(json.dumps({key: record[key] for key in ('card', 'case', 'exit_code', 'run_root')}), flush=True)
    if not records:
        parser.error('unknown selected case')
    summary = dict(build_id=build, source_unchanged=source_build_id() == build,
        cases=[{k: r[k] for k in ('card', 'case', 'exit_code', 'run_root')} for r in records],
        all_cases_executed=all(r['exit_code'] == 0 for r in records), real_model_calls=0,
        all_cards_accepted=False, functional_release=False, optimization_goal_met=False)
    write_json(REPO / 'docs/acceptance/part-three/scenario-executions.json', summary)
    return 0 if summary['all_cases_executed'] and summary['source_unchanged'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
