"""The desktop demo must run the product workflow and mark its model fixtures."""
import time
from contextlib import closing

from fastapi.testclient import TestClient
from app.api.application import create_app
from app.config import AppSettings


def test_demo_submission_reaches_verified_public_answer(tmp_path):
    # Launcher chooses this private factory only for an explicit fake environment.
    from app.runtime import demo_backend
    app = create_app(AppSettings(tmp_path, 'fixture-demo-token', 'fake', False), backend_factory=demo_backend.build_demo_backend)
    with TestClient(app, headers={'Authorization': 'Bearer fixture-demo-token'}) as client:
        cid = client.post('/v1/conversations', json={'title': '演示'}).json()['id']
        response = client.post(f'/v1/conversations/{cid}/turns', json={'text': '请保留原文件', 'domain': 'document', 'provider_profile_id': 'fake-gpt', 'client_request_id': 'req'})
        assert response.status_code == 202
        task = response.json()['task_id']
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and client.get('/v1/tasks/' + task).json()['status'] == 'pending':
            time.sleep(.05)
        assert client.get('/v1/tasks/' + task).json()['status'] == 'completed'
        messages = client.get(f'/v1/conversations/{cid}/messages').json()['items']
        answers = [item for item in messages if item['kind'] == 'answer.published']
        assert len(answers) == 1 and '演示' in answers[0]['text']
        assert '请保留原文件' in answers[0]['text']
        with closing(app.state.database.connect()) as connection:
            assert connection.execute("SELECT COUNT(*) FROM checks WHERE check_kind='A.review' AND result='pass'").fetchone()[0] == 1
            assert connection.execute("SELECT COUNT(*) FROM checks WHERE check_kind='C.criterion' AND result='pass'").fetchone()[0] == 1
            assert connection.execute('SELECT COUNT(*) FROM usage_entries').fetchone()[0] == 3


def test_demo_factory_rejected_in_real_environment(tmp_path):
    from app.runtime import demo_backend
    app = create_app(AppSettings(tmp_path, 'r' * 40, 'real', False))
    import pytest
    with pytest.raises(ValueError):
        demo_backend.build_demo_backend(app)


def test_demo_followup_keeps_original_constraint_and_attachment(tmp_path):
    from app.runtime.demo_backend import build_demo_backend
    app = create_app(AppSettings(tmp_path, 'fixture-demo-token', 'fake', False), backend_factory=build_demo_backend)
    with TestClient(app, headers={'Authorization': 'Bearer fixture-demo-token'}) as client:
        cid = client.post('/v1/conversations', json={'title': '追问'}).json()['id']
        uploaded = client.post(f'/v1/conversations/{cid}/attachments', content='附件：不删除原始数据'.encode(),
                              headers={'X-Filename': 'source.md', 'Content-Type': 'application/octet-stream'}).json()
        for key, text, attachments in [('one', '请保留原文件', [uploaded['id']]), ('two', '再增加报告', [])]:
            response = client.post(f'/v1/conversations/{cid}/turns', json={'text': text, 'domain': 'document',
                'provider_profile_id': 'fake-gpt', 'client_request_id': key, 'attachment_ids': attachments})
            task = response.json()['task_id']
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline and client.get('/v1/tasks/' + task).json()['status'] == 'pending':
                time.sleep(.05)
            assert client.get('/v1/tasks/' + task).json()['status'] == 'completed'
        answer = [x for x in client.get(f'/v1/conversations/{cid}/messages').json()['items'] if x['kind'] == 'answer.published'][-1]['text']
        assert '请保留原文件' in answer
        assert '附件：不删除原始数据' in answer
        assert '再增加报告' in answer


def test_demo_normal_document_profile_publishes_requested_native_files(tmp_path):
    from app.runtime.demo_backend import build_demo_backend
    app=create_app(AppSettings(tmp_path,'fixture-demo-token','fake',False),backend_factory=build_demo_backend)
    with TestClient(app,headers={'Authorization':'Bearer fixture-demo-token'}) as client:
        cid=client.post('/v1/conversations',json={'title':'Document normal profile'}).json()['id']
        accepted=client.post(f'/v1/conversations/{cid}/turns',json=dict(text='Keep the original file and the amount 30.',
            domain='document',provider_profile_id='fake-gpt',client_request_id='document-file',
            profile_inputs=dict(audience='Reader',purpose='Preserve the source',source_refs=['input/user_request.txt'],formats=['markdown','pdf'])))
        assert accepted.status_code==202,accepted.text
        task=accepted.json()['task_id']; deadline=time.monotonic()+30
        while time.monotonic()<deadline and client.get('/v1/tasks/'+task).json()['status']=='pending':
            time.sleep(.1)
        assert client.get('/v1/tasks/'+task).json()['status']=='completed'
        cards=client.get(f'/v1/conversations/{cid}/bundles').json()['items']
        assert len(cards)==1 and len(cards[0]['artifacts'])==2 and cards[0]['format_pairs']==[]
        answer=next(item['text'] for item in client.get(f'/v1/conversations/{cid}/messages').json()['items'] if item['kind']=='answer.published')
        assert 'Task profile inputs' not in answer and 'input/user_request.txt' not in answer
        assert 'Keep the original file and the amount 30.' in answer and 'Reader' in answer
        with closing(app.state.database.connect()) as connection:
            assert connection.execute('SELECT count(*) FROM translation_jobs WHERE task_id=?',(task,)).fetchone()[0]==0


def test_verified_relocation_replays_published_files_without_reading_old_root(tmp_path):
    import hashlib
    from app.runtime.demo_backend import build_demo_backend
    source=tmp_path/'source'; target=tmp_path/'target'; kept=tmp_path/'original-retained'
    app=create_app(AppSettings(source,'fixture-demo-token','fake',False),backend_factory=build_demo_backend)
    with TestClient(app,headers={'Authorization':'Bearer fixture-demo-token'}) as client:
        cid=client.post('/v1/conversations',json={'title':'Relocated document'}).json()['id']
        accepted=client.post(f'/v1/conversations/{cid}/turns',json=dict(text='Keep amount 30.',domain='document',
            provider_profile_id='fake-gpt',client_request_id='relocated-file',
            profile_inputs=dict(audience='Reader',purpose='Preserve source',source_refs=['input/user_request.txt'],formats=['markdown']))).json()
        task=accepted['task_id']; deadline=time.monotonic()+30
        while time.monotonic()<deadline and client.get('/v1/tasks/'+task).json()['status']=='pending': time.sleep(.1)
        assert client.get('/v1/tasks/'+task).json()['status']=='completed'
        card=client.get(f'/v1/conversations/{cid}/bundles').json()['items'][0]
        preview=client.post('/v1/storage/relocation-preview',json={'destination':str(target.resolve())})
        assert preview.status_code==200,preview.text
        moved=client.post('/v1/storage/relocate',json={'version':preview.json()['version']})
        assert moved.status_code==200 and moved.json()['verified']
    # Test-only isolation: retain the original at another checked location.
    # Published replay must work entirely from the verified new root.
    assert source.resolve().is_relative_to(tmp_path.resolve()) and kept.resolve().is_relative_to(tmp_path.resolve())
    assert not kept.exists()
    source.rename(kept)
    restarted=create_app(AppSettings(target,'fixture-demo-token','fake',False),backend_factory=build_demo_backend)
    with TestClient(restarted,headers={'Authorization':'Bearer fixture-demo-token'}) as client:
        assert client.get(f'/v1/conversations/{cid}/bundles').json()['items'][0]['bundle_id']==card['bundle_id']
        artifact=card['artifacts'][0]
        response=client.get(f'/v1/conversations/{cid}/bundles/{card["bundle_id"]}/artifacts/{artifact["artifact_id"]}/download')
        assert response.status_code==200 and hashlib.sha256(response.content).hexdigest()==artifact['sha256']
        assert any(item['kind']=='answer.published' for item in client.get(f'/v1/conversations/{cid}/messages').json()['items'])
