"""Collect observed local results and update part-one status without model calls."""
from collections import Counter
from datetime import datetime, timezone, timedelta
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
PLAN = ROOT / 'docs/superpowers/plans/2026-10-13-execution'
ACCEPTANCE = ROOT / 'docs/acceptance'
FILE_MAPPINGS = {
    'services/orchestrator/app/runtime/scheduler.py': ['services/orchestrator/app/runtime/outbox.py'],
    'tests/integration/test_state_outbox.py': ['tests/integration/test_state_machine.py', 'tests/integration/test_outbox.py'],
    'services/orchestrator/app/runtime/deduplication.py': ['services/orchestrator/app/runtime/recovery.py'],
    'tests/fixtures/recovery_events.json': ['tests/integration/test_recovery.py'],
    'services/orchestrator/app/prompts/a_contract.md': ['prompts/a_contract.md'],
    'services/orchestrator/app/prompts/b_execute.md': ['prompts/b_execute.md'],
    'services/orchestrator/app/runtime/scopes.py': ['services/orchestrator/app/runtime/workspace.py'],
    'services/orchestrator/app/runtime/write_leases.py': ['services/orchestrator/app/runtime/workspace.py'],
    'tests/integration/test_task_scopes.py': ['tests/integration/test_workspace.py', 'tests/integration/test_context_gateway.py'],
}


def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_hashes():
    sources = {}
    for area in ('services/orchestrator/app', 'tests', 'scripts', 'prompts', 'packages/contracts'):
        for path in sorted((ROOT / area).rglob('*')):
            if path.is_file() and '__pycache__' not in path.parts and path.suffix in ('.py', '.md', '.sql', '.json'):
                sources[path.relative_to(ROOT).as_posix()] = digest(path)
    for filename in ('services/orchestrator/pyproject.toml', 'services/orchestrator/uv.lock',
                     'package.json', 'package-lock.json', 'pytest.ini', '.python-version'):
        sources[filename] = digest(ROOT / filename)
    return sources


def main():
    stamp = datetime.now(timezone(timedelta(hours=8))).isoformat()
    xml = ET.parse(ACCEPTANCE / 'backend-junit.xml')
    suites = list(xml.getroot().iter('testsuite'))
    test_result = {key: sum(int(suite.get(key, '0')) for suite in suites)
                   for key in ('tests', 'failures', 'errors', 'skipped')}
    invocation = read(ACCEPTANCE / 'backend-full-test.json')
    assert invocation['exit_code'] == 0 and test_result['failures'] == test_result['errors'] == 0
    schema = read(ACCEPTANCE / 'backend-contract-check.json')
    assert schema['exit_code'] == 0
    command = [sys.executable, str(ROOT / 'tests/support/scenario_driver.py'),
               'backend_vertical', '--root', str(ROOT / '.tools/vertical-final'),
               '--options', json.dumps({'provider_mode': 'fake'})]
    actual = subprocess.run(command, cwd=ROOT, capture_output=True, text=True,
                            encoding='utf-8', errors='strict', timeout=240)
    (ACCEPTANCE / 'D020/vertical-stderr.log').write_text(actual.stderr, encoding='utf-8')
    assert actual.returncode == 0, actual.stderr
    vertical = json.loads(actual.stdout)
    assert vertical['all_local_cases_passed'] and not vertical['real_handoff_complete']
    runs = {**vertical['domains'], **vertical['faults']}
    ledgers = {}
    for name, run in runs.items():
        db_dir = Path(run['database_path']).parent
        ledgers[name] = read(db_dir / 'request-ledger.json')
        artifact = run['artifact_path']
        if artifact:
            assert Path(artifact).is_file()
        assert ledgers[name]['unknown_requests'] == run['unknown_requests']
    write(ACCEPTANCE / 'D020/vertical-report.json', {
        'generated_at': stamp, 'command': command, 'exit_code': actual.returncode,
        'boundary': 'only external model responses are fixtures; local backend and files actually execute',
        **vertical})
    write(ACCEPTANCE / 'D020/request-ledger.json', {
        'generated_at': stamp, 'provider_boundary': 'fake', 'real_model_starts': 0,
        'requests': ledgers, 'real_account_usage': 'not_verified', 'savings_claimed': False})
    sources = source_hashes()
    assert sources == read(ACCEPTANCE / 'backend-source-before.json'), 'SOURCE_CHANGED_SINCE_FINAL_TEST_START'
    write(ACCEPTANCE / 'backend-source-hashes.json', {
        'generated_at': stamp, 'hashes': sources, 'unchanged_since_final_test_start': True,
        'manifest_sha256': hashlib.sha256(json.dumps(sources, sort_keys=True).encode()).hexdigest()})
    blocked = {
        'D004': 'Claude 官方 CLI 未登录，真实身份/执行/取消/恢复未通过。',
        'D005': 'ZCode 受支持 CLI 要求先选择模型，GLM 实际身份及任务能力未通过。',
        'D020': '本地四域及故障集成已通过；必需 D004/D005 真实 A/B 贯通尚未通过。'}
    complete = [f'D{index:03}' for index in range(1, 21) if f'D{index:03}' not in blocked]
    handoff = {
        'schema_version': '1.0', 'contract_version': '1.0', 'generated_at': stamp,
        'scope': 'part one D001-D020', 'local_backend_verified': True,
        'real_handoff_complete': False, 'part_one_complete': False,
        'functional_ready': False, 'goal_validated': False,
        'completed_tasks': complete, 'blocked_tasks': blocked, 'test_result': test_result,
        'interfaces': {
            'api': 'authenticated /v1/conversations, turns, messages, events, /v1/tasks; loopback only',
            'events': 'version 1.0; public whitelist enforced for history/SSE/outbox',
            'sse': 'committed conversation cursor replay; EOF then reconnect with after_seq',
            'storage': 'SQLite WAL/FULL + transaction outbox + immutable SHA256 blobs',
            'workflow': 'injected provider, validator, reviewer and budget ports; durable contract pin and owner lease',
            'recovery': 'query/observe/verify ports for accepted external execution; unknown blocks; no restart callback',
            'current_startup_recovery': 'conservative unknown callback; no real provider query until a supported adapter is registered',
            'publication': 'trusted internal native publisher; HTTP/model visibility cannot grant approval',
            'scope': 'service path and role constraints; actual external OS sandbox remains unverified'},
        'filename_mappings': {
            'runtime/scheduler.py': 'dispatch responsibility implemented in runtime/outbox.py; workflow owns request scheduling',
            'runtime/deduplication.py': 'persistent event deduplication and gap buffering implemented in runtime/recovery.py',
            'runtime/scopes.py + runtime/write_leases.py': 'scope validation and persistent lease handoff implemented in runtime/workspace.py',
            'app/prompts/*.md': 'canonical project prompts are prompts/a_contract.md and prompts/b_execute.md'},
        'planned_to_actual_files': FILE_MAPPINGS,
        'providers': {name: read(ACCEPTANCE / card / 'supported-entry.json')
                      for name, card in [('claude', 'D004'), ('zcode', 'D005'), ('gpt', 'D006')]},
        'gpt_completion_level': 'route_decided_not_connected; native path chosen; production disabled',
        'bounded_real_startups_this_session': {'claude': 0, 'zcode': 2, 'gpt': 1, 'total': 3},
        'real_account_usage': 'unknown where provider did not report it',
        'pending_product_gates': ['Electron GUI', 'complete English input and history QA for every Claude request',
            'trusted A canonical English original capture', 'complete Chinese answer translation and QA',
            'DOCX/PDF render and layout checks', 'atomic bilingual attachment bundle publisher',
            'actual external sandbox enforcement', 'blind quality/token qualification', 'release and backup acceptance'],
        'runbook': 'docs/runbooks/backend-operations.md',
        'evidence': ['docs/acceptance/backend-full-test.log', 'docs/acceptance/backend-junit.xml',
                     'docs/acceptance/backend-source-hashes.json', 'docs/acceptance/D020/vertical-report.json',
                     'docs/acceptance/D020/request-ledger.json'],
        'git_commit': None, 'branch': 'codex/part1-foundation'}
    write(ACCEPTANCE / 'backend-handoff.json', handoff)
    board = read(PLAN / 'task-board.json')
    cards = read(PLAN / 'data/tasks-01.json')
    for task in board['tasks'] + cards:
        if task['id'] not in complete and task['id'] not in blocked:
            continue
        card = task['id']
        task['status'] = 'blocked' if card in blocked else 'done'
        task['status_updated_at'] = stamp
        task['completion_level'] = ('route_decided_not_connected' if card == 'D006' else
                                    'local_integration_verified_real_blocked' if card == 'D020' else
                                    'adapter_implemented_real_blocked' if card in blocked else 'card_scope_verified')
        if card in blocked:
            task['block_reason'] = blocked[card]
        else:
            task.pop('block_reason', None)
        task['execution_review'] = {
            'local_implementation': 'verified', 'real_acceptance': 'blocked' if card in blocked else
                'not_connected' if card == 'D006' else 'not_required_for_this_card',
            'reviewer': 'Codex root with independent native peer probes',
            'evidence': f'docs/acceptance/{card}/implementation-report.md',
            'aggregate_evidence': 'docs/acceptance/backend-handoff.json',
            'formal_merge_review': 'not_run; no merge or PR performed',
            'commit': None, 'commit_note': '原仓库无初始提交，工作区保留源码和哈希证据。'}
        extra = [f'docs/acceptance/{card}/implementation-report.md', 'docs/acceptance/backend-handoff.json']
        task['evidence'] = list(dict.fromkeys(task.get('evidence', []) + extra))
        planned = task.get('planned_deliverables', task['deliverables'])
        actual_files = [actual for filename in planned for actual in FILE_MAPPINGS.get(filename, [filename])]
        task['planned_deliverables'] = planned
        task['deliverables'] = list(dict.fromkeys(actual_files))
        assert all((ROOT / filename).is_file() for filename in task['deliverables'])
        planned_commands = task.get('planned_test_commands', task.get('test_commands', []))
        task['planned_test_commands'] = planned_commands
        for missing, mapped in FILE_MAPPINGS.items():
            if missing.startswith('tests/') and any(missing in command for command in planned_commands):
                task['test_commands'] = [
                    'services/orchestrator/.venv/Scripts/python.exe -m pytest ' + ' '.join(mapped) + ' -q']
    board['updated_at'] = stamp
    board['development_status'] = 'in_progress'
    board['execution_summary'] = {
        'scope': '部分一 D001–D020；其余 D021–D060 保留原计划状态',
        'completed_tasks': complete, 'blocked_tasks': list(blocked), 'part_one_complete': False,
        'functional_ready': False, 'goal_validated': False, 'verified_tests': test_result,
        'report': 'docs/acceptance/part-one-progress.md', 'provider_calls_made': 3,
        'provider_calls_note': '真实执行器启动次数，不等于成功模型完成或可核对token账单',
        'branch': 'codex/part1-foundation'}
    write(PLAN / 'task-board.json', board)
    write(PLAN / 'data/tasks-01.json', cards)
    index = (PLAN / 'TASK-INDEX.md').read_text(encoding='utf-8-sig')
    index = re.sub(r'状态更新：[^\n]+',
        '状态更新：2026-10-13（Asia/Shanghai）。部分一17项完成卡片范围；D004/D005真实接入、D020真实交接阻塞。D006仅路线决策完成且功能未连接。整个部分一、GUI及优化目标尚未完成。状态和证据以 task-board.json 为准。', index)
    for card in complete + list(blocked):
        status = 'blocked' if card in blocked else 'done'
        index = re.sub(rf'(^\| \[{card}\].*?\| [^|]+ \| [^|]+ \| )[^|]+( \|)',
                       lambda match: match[1] + status + match[2], index, flags=re.MULTILINE)
    (PLAN / 'TASK-INDEX.md').write_text(index, encoding='utf-8')
    audit = []
    authorized = {'docs/superpowers/plans/2026-10-13-execution/task-board.json',
                  'docs/superpowers/plans/2026-10-13-execution/data/tasks-01.json',
                  'docs/superpowers/plans/2026-10-13-execution/TASK-INDEX.md'}
    for original in read(ROOT / '.superpowers/sdd/original-files.json'):
        current = digest(ROOT / original['path'])
        changed = current != original['sha256']
        assert not changed or original['path'] in authorized
        audit.append({'path': original['path'], 'original_sha256': original['sha256'],
                      'current_sha256': current, 'changed': changed,
                      'authorized_status_update': changed and original['path'] in authorized})
    progress = {**handoff, 'updated_at': stamp, 'original_files_read': len(audit),
                'original_file_audit': audit, 'task_status_counts': dict(Counter(t['status'] for t in cards)),
                'real_model_calls': 3, 'real_model_completed_verified': 0}
    write(ACCEPTANCE / 'part-one-progress.json', progress)
    lines = ['# 部分一实施与验收报告', '',
        f'更新：{stamp}。已通读原工作区19份文件，并按既有合同实现部分一。20项中17项完成各自卡片范围，3项保留真实阻塞。D006完成等级为路线已决策、未连接。', '',
        f"最终本地回归：{test_result['tests']}项，失败{test_result['failures']}、错误{test_result['errors']}、跳过{test_result['skipped']}；真实模型标记默认排除。严格JSON Schema校验退出0。完整命令、退出码和源码哈希均已落盘。", '',
        '四域固定场景实际连接API、SQLite、不可变原件、Windows进程、验证器、用量、审批与公开事件；仅外部模型响应使用fixture。综合场景实际生成分析结果和SVG，并保存数据→代码→结果→图表→报告五节点。上游改版会使四个下游失效；旧审批不能发布。', '',
        '返修后预算阻止下一次调用；重建服务前已保存的候选、外部请求、用量和字节哈希保持一致，未知远端不重复启动。另有子进程强制退出测试覆盖事务/outbox崩溃窗口。已发布历史保留原版本，未经批准的事件、篡改的审查或B原件不能借用发布资格。', '',
        '| 卡片 | 状态 | 实际范围 |', '| --- | --- | --- |']
    for task in cards:
        card = task['id']
        note = blocked.get(card, '路线已决策，生产未连接。' if card == 'D006' else task['title'])
        lines.append(f"| {card} | {task['status']} | {note} |")
    lines += ['', '真实入口记录：Claude未登录（0次启动）；ZCode实际2次启动后仍要求先选择模型；Codex实际1次启动的工具被策略拒绝且实际model_id未知。三者均disabled，0个可核验的真实任务完成。真实用量缺失保持unknown，不写零、不声明节省。', '',
        'GUI、完整翻译、A英文原件来源、正式双语附件、质量/token盲评及发布运维验收留在D021–D060。当前part_one_complete、functional_ready、goal_validated均为false。原需求、规格和手册保持原字节；19份原文件只有任务板、部分一任务数据和任务索引发生授权状态更新。', '',
        '- [后端交接](backend-handoff.json)', '- [运行与恢复手册](../runbooks/backend-operations.md)',
        '- [全量测试日志](backend-full-test.log)', '- [四域与故障集成报告](D020/vertical-report.json)',
        '- [实际fixture用量账本](D020/request-ledger.json)', '- [源码哈希](backend-source-hashes.json)',
        '- [独立复核与修复证据](remaining-storage-recovery-review.md)',
        '- [逐项结构化进度与原文件审计](part-one-progress.json)', '',
        '变更保留在codex/part1-foundation工作区，未创建提交、合并或PR。独立复核采用原生代理和实际反例；没有声称完成正式合并审批。', '']
    (ACCEPTANCE / 'part-one-progress.md').write_text('\n'.join(lines), encoding='utf-8')
    print(json.dumps({'status': 'recorded', 'tests': test_result, 'completed': len(complete),
                      'blocked': list(blocked), 'real_handoff_complete': False}, ensure_ascii=False))


if __name__ == '__main__':
    main()
