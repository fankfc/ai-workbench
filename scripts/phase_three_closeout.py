"""Update only stage-three progress after fresh evidence; preserve older freezes."""
from collections import Counter
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tests'))
from support.manifest import source_build_id, validate_manifest, verification_source_id, write_json

CARDS = {
 'D041': ('验收 driver、真实服务和哈希证据', 'D040真实运行资格及完整装置评审'),
 'D042': ('R01–R15/T01–T20覆盖审计', '独立人工和真实供应商证据、矩阵签署'),
 'D043': ('60例翻译草案与误译拦截验证', '两名双语评审、60例独立holdout和真实双向翻译'),
 'D044': ('十二层协议草案和污染审计', '60例独立试点、功效样本量、正式评审及冻结签署'),
 'D045': ('真实产品账本重放与unknown保留', '真实逐请求供应商计量及口径审核'),
 'D046': ('联合统计门槛与生产A主导路由', '真实配对评分/用量、按配置优化资格及合格配置的运行启用范围验收'),
 'D047': ('API、路径、IPC和DOM隔离检查', '完整链接攻击矩阵及人工安全评审'),
 'D048': ('取消、千次重复、未知恢复和旧批准检查', '全部崩溃断点、文件占用与真实远端取消'),
 'D049': ('实际Electron合成输入法、键盘、缩放和瞬时泄漏检查', '实际Windows IME、Narrator与多屏人工证据'),
 'D050': ('原始延迟采样、有界持续运行和桌面生命周期runner', '全部SLO样本/负载、硬件基线、完整24小时及资源矩阵'),
 'D051': ('WAL一致备份、原件闭包、迁移、API和实际桌面恢复', '签名旧程序与匹配旧schema回滚验收'),
 'D052': ('锁定打包、便携Python运行时和内部未签名安装包', '合法签名、可信发布者及干净非管理员Windows安装'),
 'D053': ('受控更新协调器、持久日志、签名/清单前检及回滚故障矩阵', '生产原生安装/清单签名端口、真实签名包升级和兼容schema回滚演练'),
 'D054': ('Windows CI、依赖SBOM和候选清单审计', '源码提交、干净构建复现、签名/许可证与完整外部证据'),
 'D055': ('四域真实材料入口及严格证据审计', '当前真实模型身份、完整四域执行及领域人评'),
 'D056': ('反馈脱敏、格式和试用手册', '5工作日真实试用、缺陷关闭与报告者复核'),
 'D057': ('功能和优化分离的发布决策', '全部发布硬门槛、无P0/P1及产品/QA/发布三方签署'),
 'D058': ('持久保留/保护、术语历史和缓存失效控制器', '实际长期保留观察、每日备份/月度恢复及双语术语复核'),
 'D059': ('持久事故冻结、证据保护、发布阻断和重新资格检查', '真实桌面事故演练、独立新样本资格及签名兼容回滚'),
 'D060': ('离线证据索引、交接与维护日历', '干净机器第三方交接、功能/优化终验和签署')}
BLOCKED = {'D043', 'D044', 'D052', 'D053', 'D055', 'D056', 'D057', 'D060'}


def load(path):
    return json.loads((ROOT / path).read_text(encoding='utf-8-sig'))


def canonical_sha(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def main():
    verification_path = Path(sys.argv[1] if len(sys.argv) > 1 else 'docs/acceptance/part-three/final/verification.json')
    verification = load(verification_path)
    required_checks = {'contracts', 'python', 'desktop-typecheck', 'desktop-unit',
                       'desktop-build', 'desktop-test-build', 'desktop-e2e'}
    if not required_checks <= {row['name'] for row in verification.get('checks', [])}:
        raise ValueError('ALL_LOCAL_VERIFICATION_LAYERS_REQUIRED')
    if (not verification['all_executed_checks_passed'] or not verification['source_unchanged']
            or verification['build_id'] != source_build_id() or verification['qa_source_id'] != verification_source_id()):
        raise ValueError('FRESH_FINAL_VERIFICATION_REQUIRED')
    scenarios = load('docs/acceptance/part-three/scenario-executions.json')
    if (not scenarios.get('all_cases_executed') or not scenarios.get('source_unchanged')
            or scenarios.get('build_id') != verification['build_id']
            or {row['card'] for row in scenarios.get('cases', [])} != set(CARDS)
            or len(scenarios['cases']) != 20):
        raise ValueError('ALL_FINAL_SCENARIOS_REQUIRED')
    for row in scenarios['cases']:
        run_root = (ROOT / row['run_root']).resolve()
        if not run_root.is_relative_to(ROOT) or row['exit_code'] != 0:
            raise ValueError('SCENARIO_EXECUTION_INVALID')
        manifest = load(run_root / 'run-manifest.json')
        if manifest['build_id'] != verification['build_id'] or not validate_manifest(run_root, manifest)['valid']:
            raise ValueError('POST_EXIT_SCENARIO_MANIFEST_INVALID:' + row['card'])
    counts = load(verification_path.parent / 'python-counts.json')
    gui = load(verification_path.parent / 'desktop-e2e-counts.json')
    if (counts.get('tests', 0) < 1464 or any(counts.get(k, 1) != 0 for k in ('failures', 'errors', 'skipped'))
            or gui.get('expected', 0) < 35 or any(gui.get(k, 1) != 0 for k in ('unexpected', 'skipped', 'flaky'))):
        raise ValueError('FULL_LOCAL_TEST_RESULTS_REQUIRED')
    board_path = Path('docs/superpowers/plans/2026-10-13-execution/task-board.json')
    data_path = Path('docs/superpowers/plans/2026-10-13-execution/data/tasks-03.json')
    board = load(board_path)
    first40 = canonical_sha(board['tasks'][:40])
    frozen = load('docs/acceptance/part-two-freeze-20261014/preserved-state.json')
    if canonical_sha(board['tasks'][:20]) != frozen['task_groups']['part_one']:
        raise ValueError('PART_ONE_STATUS_CHANGED')
    protected = {}
    for directory in ('part-one-freeze-20261014', 'part-two-freeze-20261014'):
        for path in sorted((ROOT / 'docs/acceptance' / directory).rglob('*')):
            if path.is_file() and '__pycache__' not in path.parts:
                protected[path.relative_to(ROOT).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    now = datetime.now(timezone(timedelta(hours=8))).isoformat()
    cards = []
    current = {c['id']: c for c in load(data_path)}
    for task in board['tasks'][40:]:
        implemented, remaining = CARDS[task['id']]
        status = 'blocked' if task['id'] in BLOCKED else 'in_progress'
        detail = dict(status=status, status_updated_at=now, completion_level='local_engineering_delivered_full_acceptance_open',
            local_implementation=implemented, remaining_acceptance=remaining,
            verification=str(verification_path.as_posix()), evidence=f'artifacts/qa/{task["id"]}/local-evidence.json',
            real_model_calls=0, functional_release=False, optimization_goal_met=False)
        task.update(detail)
        current[task['id']].update(detail)
        if task['id'] == 'D053':
            additions = ['apps/desktop/src/main/update-coordinator.ts', 'tests/release/update-coordinator.test.ts']
            for record in (task, current[task['id']]):
                record['deliverables'] = list(dict.fromkeys([*record['deliverables'], *additions]))
        cards.append(dict(id=task['id'], title=task['title'], owner=task['owner'], **detail,
            next_action=remaining, verification_commands=task['test_commands']))
    board['development_status'] = 'part_three_local_engineering_verified_acceptance_open'
    board['part_three_execution_summary'] = dict(date=now[:10], user_scope='先完成本地工程并列出阻塞项',
        counts=dict(Counter(c['status'] for c in cards)), build_id=verification['build_id'],
        all_cards_accepted=False, functional_release=False, optimization_goal_met=False,
        verification=str(verification_path.as_posix()))
    if first40 != canonical_sha(board['tasks'][:40]):
        raise ValueError('PREVIOUS_CARD_GROUPS_CHANGED')
    write_json(ROOT / board_path, board)
    write_json(ROOT / data_path, [current[f'D{i:03d}'] for i in range(41, 61)])
    write_json(ROOT / 'docs/acceptance/part-three/task-results.json', dict(cards=cards, overall_goal_complete=False,
        local_scope='delivered_and_mechanically_verified', real_model_calls=0, build_id=verification['build_id']))
    preserved = all(hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == digest for name, digest in protected.items())
    write_json(ROOT / 'docs/acceptance/part-three/preserved-freezes.json', dict(first_40_cards_unchanged=True,
        first_40_cards_sha256=first40, freeze_files_unchanged=preserved, files=protected))
    index_path = ROOT / 'docs/superpowers/plans/2026-10-13-execution/TASK-INDEX.md'
    lines = [line for line in index_path.read_text(encoding='utf-8-sig').splitlines()
             if not line.startswith('阶段三更新')]
    lines = [line.replace('第一部分及 D041–D060 原样保留。', '第一部分历史冻结保留；阶段三当前状态见下表。') for line in lines]
    by_id = {c['id']: c for c in cards}
    for position, line in enumerate(lines):
        if line.startswith('| [D0'):
            identity = line.split(']')[0].split('[')[1]
            if identity in by_id:
                columns = line.split('|')
                columns[4] = ' ' + by_id[identity]['status'] + ' '
                lines[position] = '|'.join(columns)
    lines.insert(2, f'阶段三更新（{now[:10]}，Asia/Shanghai）：本轮本地实现、测试和内部未签名包已交付；12 in_progress、8 blocked，全部卡的完整终验保持开放。逐卡证据与阻塞见[阶段三报告](../../../acceptance/part-three-progress.md)。')
    index_path.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    unit_log = (ROOT / verification_path.parent / 'desktop-unit.log').read_text(encoding='utf-8')
    unit_log = re.sub(r'\x1b\[[0-9;]*m', '', unit_log)
    matched = re.search(r'\bTests\s+(\d+)\s+passed', unit_log)
    if not matched:
        raise ValueError('DESKTOP_UNIT_COUNT_MISSING')
    unit_count = int(matched[1])
    rows = '\n'.join(f'| {card["id"]} | {card["local_implementation"]} | {card["remaining_acceptance"]} |' for card in cards)
    report = f'''# 阶段三本地实施与验收记录

本轮按用户澄清“暂无，先完成本地工程并列出阻塞项”交付 D041–D060 的本地实现、验证工具和内部测试构建。第一、二部分历史冻结保留。完整阶段三终验、正式发布及质量/token优化目标继续开放；没有真实模型调用、账号操作、正式安装或分发。

本地交付包括可隔离运行的20个场景、真实服务/SQLite/文件证据、质量与身份资格审计、同一A主导的保守生产路由、桌面备份恢复、可恢复更新协调器、内部Windows包、CI/依赖清单、持久事故与保留/术语控制器及离线交接。更新协调器使用私有可信端口，外部签名/安装边界由测试端口替代。生产原生部署适配器及D051备份的更新联动、未来合格配置的优化启用仍待接入和范围验收；本轮交付不等于全部产品工程或真实更新已完成。

## 最终实际验证

Python {counts['tests']} 项通过，0失败、0错误、0跳过；默认规则排除1项 real_provider。桌面单元 {unit_count} 项、实际Electron {gui['expected']} 项通过，0失败/跳过/重试。类型检查、正式/测试构建和严格契约检查均退出0。全部统计来自本轮日志/JUnit，而不是相加各lane的重叠用例。

统一结果：[verification.json](part-three/{verification_path.parent.name}/verification.json)。构建哈希 `{verification['build_id']}`；验证装置哈希 `{verification['qa_source_id']}`；验证前后源码一致。实际命令、UTC时间、退出码和原始输出同目录保留。

20个注册场景在独立目录复跑，进程退出后全部run-manifest再次校验通过，汇总见 [scenario-executions.json](part-three/scenario-executions.json)。退出0表示实际审计或故障验证完成；其中安装、真实旅程、统计资格及发布审计仍返回未通过，不能折算为20张卡终验完成。任务板当前为12项in_progress、8项blocked、0项done。

GUI覆盖了真实回环服务、用户提问、公开回放、脚本不执行、合成composition、缩放、文件保存，以及备份ZIP全部文件哈希、真实后端PID重启和恢复后历史。合成composition不计作实际Windows IME，脚本键盘不计作Narrator/多屏人工审核。性能保留200次输入、发送/持久状态原始样本、短生命周期与短持续运行记录；30次完整冷启动、100次完整生命周期、全负载和24小时记录尚未取得资格。

内部包：[AIBroker-Setup.exe](../../dist/windows/AIBroker-Setup.exe)。包内Python实际导入/服务健康/检查点/进程清理已验证，签名为NotSigned；没有在系统中安装或对外发布。最终字节及源码树对齐见 [packaged-runtime-report.json](../../artifacts/qa/D052/packaged-runtime-report.json) 和 [authenticode.json](../../artifacts/qa/D052/authenticode.json)。

## 独立审查和修复

已关闭备份缺原件/来源清单仍被接受、恢复哈希使用迁移前值、GUI缺字段误报通过、身份角色错配、资格扩展到整个领域、私有事故配置破坏偏好保存、提交后恢复任务失败误记REJECTED等问题。精确负例、修复前记录和复验独立保留。

核心审查：[independent-core-review.md](part-three/independent-core-review.md)；更新协调器：[independent-update-review.md](part-three/independent-update-review.md)。审查限制与真实签名/安装端口边界写在各自报告中。中间失败和中断记录均保留；它们不作为最终通过证据。

## 逐卡交付及开放验收

| 卡片 | 本地交付 | 尚待工作与验收 |
| --- | --- | --- |
{rows}

所有卡的完整门槛仍未结清；逐项状态、责任角色、下一动作、命令与证据入口在 [task-results.json](part-three/task-results.json)。覆盖矩阵保留R01–R15与T01–T20，60条翻译参考仅为未审核草案；独立holdout实际数量为0。真实试点、正式统计注册、盲评与完整真实用量没有伪造。

正式发布账本中的backup_restore_missing、security_boundary_missing等，表示尚未导入绑定正式候选/源提交的合格终验报告；本地自动回归通过不自动满足这些范围更大的发布门槛。原生适配器接入、环境/权限、人工证据和长时运行分别在各卡及交接表中列明。

## 继续使用与复验

从仓库根运行 `npm run build:desktop` 后执行 `npm run desktop`；生产连接未就绪时界面显示不可用。`npm run desktop:demo` 是明确标记的本地演示。备份/恢复通过设置→存储进入，原目录保留。运维控制器、更新私有端口和真实签名接入办法见 release/ops 手册。

复验：`services/orchestrator/.venv/Scripts/python.exe scripts/phase_three_verify.py --python --desktop --output docs/acceptance/part-three/new-run`；逐场景执行 `scripts/phase_three_scenarios.py`；长时/大矩阵独立使用 `tests/performance/soak_runner.py` 和 `desktop_runner.py`，不把短测试冒充完整运行。

工程记录：[quality-report.md](part-three/quality-report.md)、[backup-report.md](part-three/backup-report.md)、[release-operations-report.md](part-three/release-operations-report.md)。[最终交接](../../release/final-handover.md) 和 [离线证据索引](../../release/offline-evidence-index.json) 保持功能/优化/整体目标为false，并列明真实连接、人评、签名、干净安装、试用和长期观察的责任与下一动作。

前两部分冻结文件及前40卡未被改写，逐文件哈希证明见 [preserved-freezes.json](part-three/preserved-freezes.json)。当前仓库仍无初始提交，以源码哈希绑定验证；未提交Git、创建PR或宣称干净提交复现已完成。
'''
    (ROOT / 'docs/acceptance/part-three-progress.md').write_text(report, encoding='utf-8')
    readme = ROOT / 'README.md'
    text = readme.read_text(encoding='utf-8-sig')
    note = f'阶段三本地更新：已交付验收装置、质量门槛、桌面备份恢复、更新协调器、内部未签名Windows包与运维控制器。本轮最终回归为 Python {counts["tests"]}、桌面单元 {unit_count}、实际Electron {gui["expected"]} 项通过；完整真实/人工/签名终验保持开放。见[阶段三报告](docs/acceptance/part-three-progress.md)。\n\n'
    if '阶段三本地更新：' in text:
        text = re.sub(r'^阶段三本地更新：[^\n]*\n\n', lambda _: note, text, count=1, flags=re.MULTILINE)
    else:
        text = text.replace('# 协作工作台\n\n', '# 协作工作台\n\n' + note, 1)
    readme.write_text(text, encoding='utf-8')
    print(json.dumps(dict(counts=board['part_three_execution_summary']['counts'], freeze_files_unchanged=preserved,
        first_40_cards_unchanged=True, functional_release=False, optimization_goal_met=False), ensure_ascii=False))


if __name__ == '__main__':
    main()
