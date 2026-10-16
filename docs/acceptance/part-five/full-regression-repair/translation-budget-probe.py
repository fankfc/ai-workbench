"""Isolated fixture-only diagnosis of serialized role prompt budget overhead."""
import asyncio
from contextlib import closing
import json
from pathlib import Path
import tempfile

from fastapi.testclient import TestClient
from app.api.application import create_app
from app.config import AppSettings
from app.runtime.answer_publication import AnswerPublisher
from test_clarification_translation import review_case
import test_output_translation as output_tests
from translation.fakes import service

results = []
for kind in ('clarification', 'output'):
    for budget in (10000, 30000):
        with tempfile.TemporaryDirectory(prefix='p5-translation-budget-') as directory:
            with TestClient(create_app(AppSettings(Path(directory), 'qa-local-token', 'fake', False))) as client:
                client.headers['Authorization'] = 'Bearer qa-local-token'
                if kind == 'clarification':
                    _, task, attempt, translation, _, _, workflow, contract = review_case(client)
                    contract['budget']['total_tokens'] = budget
                    result = asyncio.run(workflow.run(contract))
                    outcome = {'state': result.state, 'reason_codes': result.reason_codes}
                else:
                    original = output_tests.make_contract
                    def configured(*args, **kwargs):
                        contract = original(*args, **kwargs)
                        contract['budget']['total_tokens'] = budget
                        return contract
                    output_tests.make_contract = configured
                    try:
                        _, _, task, attempt, evidence, _, _ = output_tests.claude_answer.__wrapped__(client)
                    finally:
                        output_tests.make_contract = original
                    translation = service(client)
                    publisher = AnswerPublisher(translation.database_path, evidence, translation)
                    try:
                        asyncio.run(publisher.stage(task, attempt, '1.0', 'en-answer', 'translation-review'))
                        outcome = {'state': 'output_staged'}
                    except ValueError as error:
                        outcome = {'error': str(error)}
                with closing(translation.database.connect()) as connection:
                    jobs = [dict(row) for row in connection.execute(
                        "SELECT json_extract(job_json,'$.purpose') purpose,status,clarification FROM translation_jobs WHERE task_id=?", (task,))]
                results.append({'fixture': kind, 'total_tokens': budget, 'outcome': outcome,
                    'jobs': jobs, 'translator_calls': len(translation.translator.calls),
                    'checker_calls': len(translation.checker.calls), 'real_model_calls': 0})
print(json.dumps(results, indent=2))
