"""Read-only review probe: a translator reports ambiguity; checker finds none.

Product state is isolated in a temporary local service root. Provider outputs are
explicit fixtures; this probe performs no external model request.
"""
import asyncio
from contextlib import closing
from dataclasses import replace
import json
from pathlib import Path
import sys
import tempfile

REPO = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO / 'tests'))
from fastapi.testclient import TestClient
from app.api.application import create_app
from app.config import AppSettings
from translation.fakes import claude_turn, service


with tempfile.TemporaryDirectory(prefix='p5-prompt-review-') as directory:
    with TestClient(create_app(AppSettings(Path(directory), 'qa-local-token', 'fake', False))) as client:
        client.headers['Authorization'] = 'Bearer qa-local-token'
        _, task, attempt = claude_turn(client)
        translation = service(client)
        invoke = translation.translator.invoke

        async def report_ambiguity(request):
            response = await invoke(request)
            issue = dict(block_id=request.blocks[0]['block_id'], code='AMBIGUITY', severity='major',
                message='Translator cannot resolve a material source ambiguity.', source_locator=request.blocks[0]['source_locator'])
            return replace(response, findings=(issue,))

        translation.translator.invoke = report_ambiguity
        result = asyncio.run(translation.translate(task_id=task, attempt_id=attempt, source='保留原文件。',
            source_language='zh-CN', target_language='en', purpose='input'))
        with closing(translation.database.connect()) as connection:
            translator = json.loads(connection.execute("SELECT response_json FROM translation_calls WHERE job_id=? AND phase='translate'",
                (result.job_id,)).fetchone()[0])
            qa = json.loads(connection.execute('SELECT qa_json FROM translation_candidates WHERE job_id=?', (result.job_id,)).fetchone()[0])
        record = dict(provider_boundary='fixture', real_model_calls=0, result_status=result.status,
            translator_findings=translator['findings'], saved_qa_findings=qa['semantic_findings'],
            checker_calls=len(translation.checker.calls))
        output = json.dumps(record, ensure_ascii=False, indent=2) + '\n'
        destination = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).with_suffix('.json')
        if destination.exists():
            raise FileExistsError('Preserve previous review evidence; choose a fresh output path')
        destination.write_text(output, encoding='utf-8')
        print(output)
