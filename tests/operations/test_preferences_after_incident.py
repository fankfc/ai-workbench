import json

from app.operations.controller import OperationsController


def test_private_incident_settings_do_not_break_public_preferences(client):
    controller = OperationsController(client.app.state.database.path)
    identity = controller.record_incident(domains=['paper'], qualification_keys=[],
        reason='PRIVATE_INCIDENT_REASON_CANARY', evidence_blobs=[])
    settings = client.get('/v1/settings').json()
    assert set(settings['preferences']) == {'theme', 'font_size', 'send_shortcut', 'close_behavior'}
    assert 'PRIVATE_INCIDENT_REASON_CANARY' not in json.dumps(settings)
    # This is the complete object sent by the real preference form.
    changed = {**settings['preferences'], 'theme': 'dark'}
    response = client.patch('/v1/settings', json=dict(expected_version=settings['version'], preferences=changed))
    assert response.status_code == 200
    assert response.json()['preferences']['theme'] == 'dark'
    assert controller.view()['incidents'][identity]['status'] == 'open'
    assert controller.view()['incidents'][identity]['reason'] == 'PRIVATE_INCIDENT_REASON_CANARY'
