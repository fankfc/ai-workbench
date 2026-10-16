"""Run real translation QA on fixture bytes, separately audit human readiness."""
import asyncio
import json
from pathlib import Path

from fastapi.testclient import TestClient
from app.api.application import create_app
from app.config import AppSettings
from app.translation.protection import protect
from app.translation.quality import evaluate
from app.translation.segments import segment_document
from support.manifest import write_json

OPTIONS_SCHEMA = dict(type='object', additionalProperties=False, properties={
    'fault': dict(enum=['critical_semantic']), 'case_id': dict(type='string'), 'candidate': dict(type='string')})
RESULT_SCHEMA = dict(type='object', required=['published', 'issue_codes', 'reviewed_blocks', 'expected_blocks', 'translator_calls'])
REPO = Path(__file__).resolve().parents[3]


def _check(row, candidate, *, semantic_findings=(), semantic_complete=False):
    segments = segment_document(row['source'], format='text')
    protected = tuple(protect(segment) for segment in segments)
    # A single source block is used in these drafts. Replacement protects exact
    # source bytes; any changed number/path leaves the original marker missing.
    blocks = {}
    if len(segments) == 1:
        value = candidate
        for span in protected[0].spans:
            value = value.replace(span.raw, span.marker, 1)
        blocks[segments[0].block_id] = value
    findings = [dict(block_id=segments[0].block_id, code=code, severity='critical', message='Explicit known adversarial fixture finding; not human or model evidence.', source_locator=segments[0].source_locator) for code in semantic_findings]
    qa, targets, ready = evaluate(row['id'], 'draft', segments, protected, blocks,
        semantic_findings=findings, semantic_complete=semantic_complete, complete=True,
        format='text', target_language='en' if row['direction'] == 'zh-en' else 'zh-CN')
    return dict(case_id=row['id'],ready=ready,issue_codes=[f.code for f in qa.semantic_findings],
                qa=qa.model_dump(mode='json'),reference_status=row['reference_status'])


def run(root, options):
    rows = [json.loads(line) for line in (REPO / 'tests/fixtures/translation/golden.jsonl').read_text(encoding='utf-8').splitlines()]
    checks = [_check(row, row['approved_reference']) for row in rows]
    negative_checks = [_check(row, row['negative_candidate'], semantic_findings=row.get('expected_issues', []), semantic_complete=True)
                       for row in rows if row.get('negative_candidate')]
    issues = {'HUMAN_REVIEW_MISSING', 'INDEPENDENT_HOLDOUT_MISSING', 'REAL_CLAUDE_SCENARIOS_UNVERIFIED'}
    case_id = options.get('case_id')
    if case_id:
        aliases = {'en-zh-negation-number':'neg-num','zh-en-code-and-condition':'code-draft-01','en-zh-uncertainty-citation':'paper-draft-01'}
        row = next((r for r in rows if r['id'] == aliases.get(case_id,case_id)), None)
        if row is None:
            raise ValueError('UNKNOWN_TRANSLATION_CASE')
        if 'candidate' not in options:
            raise ValueError('CANDIDATE_REQUIRED')
        # Expected fixture findings are only attributed to the exact known
        # negative. Arbitrary candidates cannot pass without independent review.
        known = options['candidate'] == row.get('negative_candidate')
        check = _check(row, options['candidate'], semantic_findings=row.get('expected_issues', []) if known else [], semantic_complete=known)
        negative_checks.append(check)
        issues.update(check['issue_codes'])
    elif 'candidate' in options:
        raise ValueError('CASE_ID_REQUIRED')
    if options.get('fault') == 'critical_semantic':
        issues.update(code for c in negative_checks for code in c['issue_codes'])
    # Verify the product GPT native-language branch with actual translation
    # service; fake model ports are present solely to count invocations.
    from translation.fakes import service
    app = create_app(AppSettings(Path(root) / 'native-translation', 'corpus-qa-local-token', 'fake', False))
    with TestClient(app) as client:
        client.headers['Authorization'] = 'Bearer corpus-qa-local-token'
        from contextlib import closing
        with closing(app.state.database.connect()) as connection:
            connection.execute("UPDATE provider_profiles SET identity_status='verified',identity_source='fixture:fake' WHERE id='fake-gpt'")
        cid = client.post('/v1/conversations', json={'title':'GPT 原语言验证'}).json()['id']
        task_id = client.post(f'/v1/conversations/{cid}/turns', json=dict(text='保留中文原文',provider_profile_id='fake-gpt',client_request_id='native-corpus')).json()['task_id']
        with closing(app.state.database.connect()) as connection:
            attempt = connection.execute('SELECT attempt_id FROM task_runs WHERE task_id=?',(task_id,)).fetchone()[0]
        translation = service(client)
        native = asyncio.run(translation.translate(task_id=task_id,attempt_id=attempt,source='保留中文原文',source_language='zh-CN',target_language='en',purpose='input'))
        calls = len(translation.translator.calls)
    holdout = json.loads((REPO / 'quality/translation-holdout-manifest.json').read_text(encoding='utf-8'))
    result = dict(published=False, issue_codes=sorted(issues), reviewed_blocks=sum(r['reference_status'] == 'approved' and len(r.get('reviewers', [])) >= 2 for r in rows),
        expected_blocks=len(rows), translator_calls=calls, gpt_native_status=native.status,
        product_evaluations=len(checks)+len(negative_checks), critical_negative_rejected=sum(not c['ready'] for c in negative_checks),
        human_review_complete=False, holdout_sample_count=len(holdout['samples']),
        automated_checks_only=True, provider_boundary='fake',real_provider_verified=False)
    write_json(Path(root) / 'translation-corpus-report.json', result)
    write_json(Path(root) / 'product-qa-checks.json', dict(drafts=checks,known_negative_fixtures=negative_checks))
    return result
