"""Reproducible unreviewed fixture drafts, never human/real-model evidence."""
import csv
import hashlib
import json
from pathlib import Path
import sys

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / 'services/orchestrator'))
from app.quality.eligibility import DIMENSIONS, DOMAINS, DIFFICULTIES, canonical_hash, registration_hash


def write(path, value):
    target = REPO / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


original = [
 dict(id='neg-num', domain='code', direction='en-zh', source='Do not release when delta < -0.03.', approved_reference='当差值小于 -0.03 时，禁止发布。', protected_spans=[], required_facts=['prohibition','threshold=-0.03','comparison=less_than'], ambiguities=[], negative_candidate='当差值小于 0.03 时允许发布。', expected_issues=['NEGATION_CHANGED','NUMBER_CHANGED']),
 dict(id='uncertain', domain='paper', direction='en-zh', source='This may improve accuracy; it has not been proven.', approved_reference='这可能提高准确率；但尚未得到证明。', protected_spans=[], required_facts=['uncertainty','not_proven'], ambiguities=[], negative_candidate='这已经被证明能提高准确率。', expected_issues=['UNCERTAINTY_CHANGED']),
 dict(id='valid', domain='document', direction='en-zh', source='Keep the original file. The estimate is 95%.', approved_reference='保留原文件。估计值为 95%。', protected_spans=[], required_facts=['preserve_original','estimate=95%'], ambiguities=[], expected_issues=[]),
]
pairs = {
 'code': [
 ('仅当 `n >= 10` 时运行；不要修改路径 `C:\\data\\原始.csv`。保留命令 `python app.py --dry-run`。', 'Run only when `n >= 10`; do not modify the path `C:\\data\\原始.csv`. Preserve the command `python app.py --dry-run`.'),
 ('Do not overwrite `input/raw.csv`; write results to `output/report.csv`.', '不要覆盖 `input/raw.csv`；将结果写入 `output/report.csv`。'),
 ('取消后不要启动第二次请求。', 'Do not start a second request after cancellation.'),
 ('Retry only if the remote status is confirmed as not started.', '仅在确认远端状态为尚未启动时重试。'),
 ('当记录为空时返回空列表，而不是错误。', 'Return an empty list rather than an error when there are no records.'),
 ('A timeout does not establish that the operation failed.', '超时并不能证明操作已经失败。'),
 ('保留变量 `customer_id` 和函数 `validate_csv` 的原名。', 'Preserve the original variable name `customer_id` and function name `validate_csv`.'),
 ('Use `UTF-8` and retain Chinese column names.', '使用 `UTF-8` 并保留中文列名。'),
 ('仅接受 `GET /v1/tasks`，拒绝未知命令。', 'Accept only `GET /v1/tasks` and reject unknown commands.'),
 ('The cache must expire when the policy version changes.', '策略版本变化时，缓存必须失效。'),
 ('失败和取消产生的用量均应计入。', 'Usage from both failed and cancelled attempts must be counted.'),
 ('Validate a 100 MB attachment before admitting it.', '在接收前验证大小为 100 MB 的附件。'),
 ('保留表达式 `$x <= 0$` 和负号。', 'Preserve the expression `$x <= 0$` and its sign.'),
 ('Do not publish an incomplete bilingual bundle.', '不要发布不完整的双语交付包。'),
 ('若文件哈希不一致，保留当前数据并拒绝恢复。', 'If the file hash differs, retain current data and reject restoration.'),
 ('The limit is 500 ms, including local cancellation feedback.', '限制为 500 ms，包括本地取消反馈。'),
 ('用两个独立工作区测试同名文件隔离。', 'Test isolation of identically named files using two independent workspaces.'),
 ('A successful process exit alone is insufficient evidence.', '单凭进程成功退出不足以构成证据。'),
 ('列出假适配器限制，不声明真实模型已验证。', 'List the limitations of the fake adapter without claiming that real models have been verified.'),
 ],
 'paper': [
 ('该研究并未确立因果关系[12]。估计值为 -0.03（95% 置信区间：-0.07 至 0.01）。', 'The study did not establish causation [12]. The estimate was -0.03 (95% CI: -0.07 to 0.01).'),
 ('The sample size is 60 independent participants, not 60 repeated measurements.', '样本量为 60 名独立受试者，而非 60 次重复测量。'),
 ('保留引用 `[12]`，不要编造文献来源。', 'Preserve the citation `[12]` and do not fabricate bibliographic sources.'),
 ('The observed association may reflect confounding.', '观察到的关联可能反映混杂因素。'),
 ('表格的单位为 `mg`；不得转换为 `g` 后遗漏倍率。', 'The table uses `mg`; do not convert it to `g` and omit the scale factor.'),
 ('A 95% confidence level does not permit a 5% loss of quality.', '95% 的置信水平不意味着允许损失 5% 的质量。'),
 ('零观察错误并不保证未来绝对零错误。', 'Zero observed errors does not guarantee zero future errors.'),
 ('Report the lower and upper interval bounds, including negative signs.', '报告区间下界和上界，并保留负号。'),
 ('仅在方法满足独立性条件时应用检验。', 'Apply the test only when its independence assumptions hold.'),
 ('Do not treat a pilot sample as an unseen holdout.', '不要将试点样本视为未见的留出样本。'),
 ('量表、样本量和停止规则必须在看正式结果之前登记。', 'Register the rubric, sample size, and stopping rule before inspecting formal results.'),
 ('Figure 2 supports the trend but does not establish the mechanism.', '图 2 支持该趋势，但并未确立其机制。'),
 ('正文、表格、图注和附录均须完整覆盖。', 'Cover the main text, tables, figure captions, and appendices in full.'),
 ('The estimate is uncertain; the interval includes zero.', '该估计存在不确定性；区间包含零。'),
 ('保留公式 `$p < 0.05$`，不将其改为等号。', 'Preserve the formula `$p < 0.05$` without changing it to equality.'),
 ('Randomize execution order and conceal model labels from reviewers.', '随机化执行顺序，并向评审隐藏模型标签。'),
 ('未核实来源应标记为未验证。', 'Mark unverified sources as unverified.'),
 ('The paired quality difference must have a lower bound of at least zero.', '配对质量差的下界必须不低于零。'),
 ('统计结论与原始数据版本必须一致。', 'Statistical conclusions must correspond to the version of the original data.'),
 ],
 'document': [
 ('只保存经批准的同版本中英文文件。', 'Save only approved Chinese and English files from the same version.'),
 ('English and Chinese page counts may differ.', '英文版和中文版页数可以不同。'),
 ('不要隐藏译文渲染失败。', 'Do not conceal translation rendering failures.'),
 ('Preserve footnote 1 and its connection to the paragraph.', '保留脚注 1 及其与段落的对应关系。'),
 ('目录不得替代完整正文。', 'A table of contents must not replace the full document body.'),
 ('A complete English canonical document must actually be produced by A.', '完整的英文定稿必须确由 A 输出。'),
 ('术语有两种含义时先请求澄清。', 'Request clarification first when a term has two meanings.'),
 ('Do not mix the English file from version 3 with the Chinese file from version 2.', '不要将第 3 版英文文件与第 2 版中文文件混合配对。'),
 ('恢复前核对所有文件的 `SHA-256`。', 'Verify the `SHA-256` of every file before restoration.'),
 ('Report missing glyphs and table overflow before publication.', '发布前报告缺字和表格溢出。'),
 ('正文中引用的数据单位为 `kg`。', 'The data referenced in the text use `kg`.'),
 ('The plan is proposed and has not received human approval.', '该计划为提议方案，尚未获得人工批准。'),
 ('标题、段落、列表和表格顺序保持不变。', 'Keep the order of headings, paragraphs, lists, and tables unchanged.'),
 ('Do not include credentials in the exported feedback bundle.', '不要在导出的反馈包中包含凭证。'),
 ('只有用户本次明确选择后才附带正文。', 'Attach document contents only after the user explicitly chooses to include them for this instance.'),
 ('An unsigned test build must not be described as a signed release.', '不得将未签名测试构建描述为已签名发布版本。'),
 ('把未完成项的责任人与下一动作列出。', 'List the owner and next action for each unfinished item.'),
 ('Keep the original evidence when a new version is issued.', '发布新版本时保留原始证据。'),
 ('中文路径 `C:\\资料\\报告.pdf` 必须逐字保留。', 'Preserve the Chinese path `C:\\资料\\报告.pdf` exactly.'),
 ]
}
rows = list(original)
for domain, values in pairs.items():
    for index, (source, target) in enumerate(values, 1):
        direction = 'zh-en' if any('\u3400' <= c <= '\u9fff' for c in source) else 'en-zh'
        protected = []
        import re
        protected.extend(re.findall(r'`[^`]+`', source))
        rows.append(dict(id=f'{domain}-draft-{index:02}', domain=domain, direction=direction,
            source=source, approved_reference=target, protected_spans=protected,
            required_facts=['complete_source_semantics', 'preserve_scope_and_certainty'],
            ambiguities=[], expected_issues=[], severity_definition='critical: negation, condition, quantity, provenance or required-block change'))
for row in rows:
    row['reference_status'] = 'unreviewed_draft'
    row['reviewers'] = []
    row['draft_author'] = 'Codex'
    row.setdefault('severity_definition', 'critical: negation, condition, quantity or certainty change')
assert len(rows) == 60
target = REPO / 'tests/fixtures/translation/golden.jsonl'
target.write_text(''.join(json.dumps(row, ensure_ascii=False) + '\n' for row in rows), encoding='utf-8')
(REPO / 'quality').mkdir(exist_ok=True)
with (REPO / 'quality/translation-review-form.csv').open('w', newline='', encoding='utf-8') as stream:
    writer = csv.writer(stream)
    writer.writerow(['case_id','domain','direction','reviewer_1','reviewer_2','negation','scope','numbers_units','citations','block_coverage','decision','adjudicator','evidence_ref'])
    writer.writerows([r['id'],r['domain'],r['direction'],'','','unreviewed','unreviewed','unreviewed','unreviewed','unreviewed','pending','',''] for r in rows)
write('quality/translation-holdout-manifest.json', dict(version='1.0-draft', status='awaiting_independent_custodian', required_samples=60, samples=[], body_policy='held_outside_repository_and_B_workspace', independence_verified=False, reviewers=[], actual_sample_count=0))

path_map = {'T01':'tests/integration/test_input_translation.py','T02':'tests/translation/test_quality_cache.py','T03':'tests/unit/test_language_router.py','T04':'tests/integration/test_route_snapshot.py','T05':'tests/integration/test_clarification_translation.py','T06':'tests/translation/test_segments.py','T07':'tests/artifacts/test_document_parse.py','T08':'tests/translation/test_pipeline_contract.py','T09':'tests/translation/test_quality_cache.py','T10':'tests/integration/test_output_translation.py','T11':'tests/artifacts/test_atomic_publication.py','T12':'tests/integration/test_dependency_invalidation.py','T13':'tests/artifacts/test_canonical_provenance.py','T14':'tests/artifacts/test_bilingual_generation.py','T15':'tests/artifacts/test_render_layout.py','T16':'tests/integration/test_context_gateway.py','T17':'tests/artifacts/test_document_parse.py','T18':'tests/translation/test_late_receipts.py','T19':'tests/e2e/chat-publication.spec.ts','T20':'tests/translation/test_glossary_content_cache.py'}
maps = {'T01':['R07','R15'],'T02':['R10'],'T03':['R03'],'T04':['R03','R12'],'T05':['R07','R08','R15'],'T06':['R07','R15'],'T07':['R09','R15'],'T08':['R07','R15'],'T09':['R07','R14'],'T10':['R08','R12'],'T11':['R09','R12'],'T12':['R09','R12'],'T13':['R09'],'T14':['R09'],'T15':['R09'],'T16':['R07','R11'],'T17':['R07','R15'],'T18':['R08','R12'],'T19':['R11'],'T20':['R15']}
spec = (REPO / 'docs/superpowers/specs/2026-10-13-translation-delivery-spec.md').read_text(encoding='utf-8')
cases=[]
for case_id,path in path_map.items():
    original_row = next(line for line in spec.splitlines() if line.startswith('| '+case_id+' |'))
    cases.append(dict(case_id=case_id,path=path,owner='翻译 QA',kind='automatic',platform='Windows x64' if path.endswith('.ts') else 'Python local',polarity='positive_and_negative',requirements=maps[case_id],mandatory=True,acceptance_status='not_verified',evidence=[],command=('npx playwright test '+path) if path.endswith('.ts') else ('python -m pytest '+path+' -q'),source_row=original_row))
extra = [
 ('QUALITY_REAL',['R01','R02'],'real_provider','quality/evaluation-registration.json','评测负责人','按 quality/evaluation-protocol.md 采集配对真实样本'),
 ('PROVIDER_REAL',['R03','R04'],'real_provider','docs/acceptance/part-two-freeze-20261014/unfinished-tasks.json','接入工程师','执行 D004/D005/D020/D024/D040 真实接入验收'),
 ('JOURNEYS_REAL',['R05'],'real_provider','quality/real-journeys.json','产品验收负责人','按 D055 运行四类真实任务'),
 ('GUI_MANUAL',['R06'],'human','quality/gui-manual-checks.csv','桌面 QA','实际 IME/Narrator/多屏验收'),
 ('INSTALL_SIGNED',['R13'],'human','release/backup-restore-runbook.md','发布工程师','执行 D051-D054 真实备份、签名、安装与回滚'),
 ('LEDGER_REAL',['R14'],'real_provider','quality/usage-reconciliation.csv','评测数据审核','实际提供方回执与请求账本逐项对照'),
 ('TRANSLATION_HUMAN',['R07','R08','R09','R15'],'human','quality/translation-review-form.csv','双语领域评审','两名独立评审复核 golden 与独立 holdout'),
]
for cid,rs,kind,path,owner,cmd in extra:
    cases.append(dict(case_id=cid,requirements=rs,kind=kind,path=path,owner=owner,command=cmd,platform='Windows x64',polarity='positive_and_negative',mandatory=True,acceptance_status='not_verified',evidence=[]))
source=json.loads((REPO / 'docs/decisions/requirements-v1.json').read_text(encoding='utf-8'))
records=[]
for item in source['requirements']:
    records.append(dict(id=item['id'],statement=item['statement'],source=item['source'],mandatory=True,gate='optimization' if item['id'] in ('R01','R02') else 'functional',owner=item['acceptance_owners'],mandatory_cases=[c['case_id'] for c in cases if item['id'] in c['requirements']],acceptance_status='not_verified'))
matrix=dict(version='1.0',source='docs/decisions/requirements-v1.json',source_sha256=hashlib.sha256((REPO / 'docs/decisions/requirements-v1.json').read_bytes()).hexdigest(),requirements=records,created_by='Codex',human_signoff='not_claimed')
write('quality/requirements-matrix.json',matrix)
regression=dict(version='1.0',change_reason='Initial phase-three inventory, preserves unverified real/manual acceptance',requirements_matrix_sha256=canonical_hash(matrix),cases=cases,skip_policy='skipped_xfail_missing_manual_or_real_remain_unverified')
regression['sha256']=canonical_hash(regression)
write('quality/regression-manifest.json',regression)
registration=dict(version='1.0-draft',status='draft',frozen_at=None,analysis_at=None,
    statistics=dict(method='paired_hoeffding_bonferroni',alpha=.05,family_comparisons=84,dimensions=list(DIMENSIONS),quality_score_range=[0,1],quality_lower_bound_min=0,token_saving_lower_bound_strict_min=0),
    scopes=[dict(domain=d,difficulty=level,pilot_required=5,formal_sample_size=None,max_a_tokens=None,configuration=None) for d in DOMAINS for level in DIFFICULTIES],
    pilots=[],power_analysis=None,stopping_rule='one_fixed_analysis_no_optional_stopping',
    reviewers=[],adjudicator=None,signatures=[],holdout_ids=[],tuning_ids=[],
    failure_policy='include_all_attempts_zero_failed_quality',equal_materials_tools_deliverables=True,a_canonical_required=True,
    protocol_file_sha256=hashlib.sha256((REPO / 'quality/evaluation-protocol.md').read_bytes()).hexdigest())
registration['registration_sha256']=registration_hash(registration)
write('quality/evaluation-registration.json',registration)
write('quality/holdout-manifest.json',dict(version='1.0-draft',status='not_collected',samples=[],pilot_samples_required=60,formal_sample_sizes='must_register_after_independent_pilot_and_power_analysis',body_policy='custodian_only_no_B_access',independence_verified=False))

events=[]
def event(group,**extras):
    value=dict(group=group,source_kind='synthetic',provider_profile_id='fixture-gpt',external_request_id='request',event_id='event',provider='gpt',raw={'total_tokens':120},source='reported',mode='request_total',sequence=1,role='A',function='execution',domain='code',status='completed')
    value.update(extras); events.append(value)
event('duplicate'); event('duplicate')
for index,total in enumerate([100,180,250],1):
    event('cumulative',external_request_id='request'+str(index),event_id='counter'+str(index),raw={'total_tokens':total},mode='cumulative',sequence=index,cumulative_scope='synthetic-session')
event('unknown',raw={},source='unknown')
event('estimated',source='estimated')
for index,(role,fn,status) in enumerate([('B','execution','failed'),('B','translation','cancelled'),('A','review','completed'),('A','takeover','completed'),('A','execution','completed')]):
    event('all_costs',external_request_id='cost'+str(index),event_id='cost-event'+str(index),role=role,function=fn,status=status,raw={'total_tokens':10})
(REPO / 'tests/fixtures/usage').mkdir(parents=True,exist_ok=True)
(REPO / 'tests/fixtures/usage/provider-events.jsonl').write_text(''.join(json.dumps(e)+'\n' for e in events),encoding='utf-8')
with (REPO / 'quality/usage-reconciliation.csv').open('w',newline='',encoding='utf-8') as stream:
    writer=csv.writer(stream); writer.writerow(['provider','wire_protocol','source_kind','actual_events','usage_verified','limitation'])
    writer.writerows([['claude','anthropic','external_missing',0,False,'D004/D020 real acceptance missing'],['glm','unqualified','external_missing',0,False,'D005 POST405 unresolved'],['gpt','unqualified','external_missing',0,False,'current runtime lifecycle not qualified']])
write('quality/optimization-eligibility.json',dict(version='1.0',status='evidence_insufficient',eligible=False,optimization_goal_met=False,route='a_led',qualified_configurations=[],registration_sha256=registration['registration_sha256'],blocked_reasons=['INDEPENDENT_PILOTS_MISSING','FORMAL_PROTOCOL_NOT_FROZEN','REAL_PAIRED_SCORES_MISSING','REAL_A_USAGE_MISSING','HUMAN_REVIEW_MISSING']))
