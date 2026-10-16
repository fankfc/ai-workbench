import json
from contextlib import closing

import pytest

from conftest import capture, record_a_response


@pytest.mark.parametrize('text,kwargs,code', [
    ('PASS', {}, 'A_CANONICAL_REQUIRED'),
    ('# Report\n\nActual body.', {'role': 'B'}, 'A_RESPONSE_STEP_REQUIRED'),
    ('# Report\n\nActual body.', {'completed': False}, 'A_RESPONSE_NOT_COMPLETE'),
    ('# Report\n\nActual body.', {'chunks': ['# Other body']}, 'A_RESPONSE_BODY_MISMATCH'),
])
def test_only_full_complete_trusted_a_body_can_be_canonical(document_task, text, kwargs, code):
    from app.documents.canonical import CanonicalCapture
    ctx = document_task
    sid = record_a_response(ctx, text, **kwargs)
    with pytest.raises(ValueError, match=code):
        CanonicalCapture(ctx['client'].app.state.database.path).capture(ctx['task'], ctx['attempt'], sid, language='en')


def test_capture_keeps_raw_stream_body_hash_and_immutable_provenance(document_task):
    from app.documents.canonical import require_canonical
    ctx = document_task
    text = '# Report\n\nJanuary 30. February 40. Increase 10.\n'
    result = capture(ctx, text)
    client = ctx['client']
    with closing(client.app.state.database.connect()) as c:
        proof = require_canonical(c, client.app.state.blobs, result['revision_id'])
        assert client.app.state.blobs.read(proof['body_sha256']).decode() == text
        raw = json.loads(client.app.state.blobs.read(proof['raw_response_sha256']))
        assert raw[-1]['kind'] == 'model.completed'
        assert raw[-1]['payload']['text'] == text
        assert proof['step_id'] == result['step_id']
        with pytest.raises(Exception, match='IMMUTABLE'):
            c.execute("UPDATE a_document_responses SET body_sha256=?", ('f'*64,))


def test_multipart_manifest_does_not_allow_omitted_or_duplicate_parts(document_task):
    ctx = document_task
    with pytest.raises(ValueError, match='MANIFEST'):
        capture(ctx, '# Report\n\nBody.', manifest={'part_count': 2, 'part_numbers': [1, 1], 'complete': True})
