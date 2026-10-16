"""Inspect the actual A no-progress takeover request with Chinese C evidence."""
import asyncio
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sys
import tempfile

REPO = Path(__file__).resolve().parents[4]
sys.path[:0] = [str(REPO / 'tests'), str(REPO / 'tests/integration')]
from fastapi.testclient import TestClient
from app.api.application import create_app
from app.config import AppSettings
from support.contracts import make_contract
from test_claude_native_pipeline import assembly, mechanical
from translation.fakes import claude_turn


with tempfile.TemporaryDirectory(prefix='p5-language-review-') as directory:
    with TestClient(create_app(AppSettings(Path(directory), 'qa-local-token', 'fake', False))) as client:
        client.headers['Authorization'] = 'Bearer qa-local-token'
        _, task, attempt = claude_turn(client)
        translation, manager, worker, reviewer, workflow = assembly(client, task, attempt)
        candidate = dict(text='Keep the original file.', language='en', usage={'total_tokens': 8})
        worker.executions = [candidate.copy(), candidate.copy()]
        reviewer.takeovers = [candidate.copy(), candidate.copy(), candidate.copy()]
        defect = dict(id='DEF-REVIEW', requirement_id='AC2', location='b/result', impact='An unresolved semantic issue.',
            required_change='Repair the reported issue.', pass_condition='A checks the corrected result.')
        base = dict(canonical_author='A', read_unit_ids=['USER-1'], usage={'total_tokens': 9})
        reviewer.reviews = [dict(**base, decision='REPAIR', findings=[defect]),
            dict(**base, decision='REPAIR', findings=[defect]),
            dict(**base, decision='PASS', criterion_results={'AC2': True})]
        workspace = manager.create(task, attempt)
        raw = '保留原文件。'.encode()
        workspace.ingest_source('request.md', raw)
        with closing(translation.database.connect()) as connection:
            route = json.loads(connection.execute('SELECT route_snapshot_json FROM task_runs WHERE task_id=?', (task,)).fetchone()[0])
        contract = make_contract(task, attempt, route['id'], 'mixed', 'claude')
        contract['budget'] = dict(total_tokens=300000, reserved_a_tokens=60000)
        contract['inputs'] = [dict(id='USER-1', ref='input/request.md', sha256=hashlib.sha256(raw).hexdigest())]
        contract['source_unit_ids'] = ['USER-1']
        contract['full_read_required'] = True

        def observed(candidate):
            result = mechanical(candidate)
            for item in result:
                item['evidence']['note'] = '禁止删除原始文件。'
            return result

        workflow.validator = observed
        result = asyncio.run(workflow.run(contract))
        prompts = [json.loads(Path(request.prompt_path).read_text(encoding='utf-8')) for request in reviewer.starts]
        takeovers = [prompt for prompt in prompts if prompt['phase'] == 'takeover' and 'repair_work_order' in prompt['evidence_package']]
        order = takeovers[0]['evidence_package']['repair_work_order'] if takeovers else {}
        record = dict(provider_boundary='fixture', real_model_calls=0, state=result.state, reason_codes=result.reason_codes,
            review_requests=sum(prompt['phase'] == 'review' for prompt in prompts),
            takeover_requests=sum(prompt['phase'] == 'takeover' for prompt in prompts),
            repair_takeover_requests=len(takeovers),
            raw_chinese_note_in_takeover='禁止删除原始文件。' in json.dumps(order, ensure_ascii=False),
            english_translated_note_in_review=any('Do not delete original files.' in json.dumps(prompt, ensure_ascii=False)
                for prompt in prompts if prompt['phase'] == 'review'))
        output = json.dumps(record, ensure_ascii=False, indent=2) + '\n'
        destination = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).with_suffix('.json')
        if destination.exists():
            raise FileExistsError('Preserve previous review evidence; choose a fresh output path')
        destination.write_text(output, encoding='utf-8')
        print(output)
