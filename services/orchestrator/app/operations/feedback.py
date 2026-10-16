"""Exercise existing allowlisted diagnostics without exporting chat content."""
import io
import json
import zipfile
from fastapi.testclient import TestClient
from app.api.application import create_app
from app.config import AppSettings
from app.usage.ledger import UsageLedger


CANARIES = ('PRIVATE_TITLE_CANARY', 'PRIVATE_BODY_CANARY', 'RAW_SECRET_CANARY', 'FEEDBACK_TOKEN_CANARY')


def build_feedback(root, *, include_content=False, content_opt_in=False):
    root.mkdir(parents=True, exist_ok=True)
    app = create_app(AppSettings(root / 'product', CANARIES[3], 'fake', False))
    with TestClient(app) as client:
        client.headers['Authorization'] = 'Bearer ' + CANARIES[3]
        conversation = client.post('/v1/conversations', json={'title': CANARIES[0]}).json()['id']
        response = client.post(f'/v1/conversations/{conversation}/turns', json={'text': CANARIES[1], 'provider_profile_id': 'fake-gpt', 'client_request_id': 'feedback-canary'})
        response.raise_for_status()
        task = response.json()['task_id']
        with app.state.database.connect() as connection:
            attempt = connection.execute('SELECT attempt_id FROM task_runs WHERE task_id=?', (task,)).fetchone()[0]
        UsageLedger(app.state.database.path).record(task_id=task, attempt_id=attempt, provider_profile_id='fake-gpt',
            external_request_id='diagnostics-canary', event_id='diagnostics-canary', provider='gpt',
            raw={'secret': CANARIES[2]}, source='unknown', mode='request_total', sequence=1,
            role='A', function='execution', domain='mixed', status='failed')
        response = client.post('/v1/diagnostics/export')
        response.raise_for_status()
        (root / 'feedback-diagnostics.zip').write_bytes(response.content)
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        text = '\n'.join(archive.read(name).decode('utf-8') for name in archive.namelist())
    # This probe has no human opting in. A CLI boolean is never consent to export
    # private product material; selected-content export stays a UI follow-up.
    reasons = ['content_opt_in_required'] if include_content else []
    return dict(secret_leaks=[value for value in CANARIES if value in text],
                contains_user_content=CANARIES[1] in text, explicit_content_opt_in=False,
                reproducible_case=response.status_code == 200, evidence_kind='deterministic_product_probe',
                blocked_reasons=reasons)

