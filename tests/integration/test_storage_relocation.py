"""A relocation is a verified copy followed by a managed backend restart."""
from pathlib import Path
from fastapi.testclient import TestClient
from app.api.application import create_app
from app.config import AppSettings


def test_relocation_copies_database_blobs_and_workspace_then_requires_restart(client, tmp_path):
    source = client.app.state.settings.data_root
    target = tmp_path.parent / (tmp_path.name + '-new-data')
    cid = client.post('/v1/conversations', json={'title': '迁移后仍在'}).json()['id']
    blob = client.app.state.blobs.put('不可变材料'.encode())
    workspace = source / 'workspaces' / 'test' / 'input'
    workspace.mkdir(parents=True)
    (workspace / 'source.md').write_text('保留全部材料', encoding='utf-8')
    plan = client.post('/v1/storage/relocation-preview', json={'destination': str(target)})
    assert plan.status_code == 200 and plan.json()['ready'] is True
    moved = client.post('/v1/storage/relocate', json={'version': plan.json()['version']})
    assert moved.status_code == 200
    result = moved.json()
    assert result['verified'] is True and result['restart_required'] is True
    assert source.is_dir() and target.is_dir()
    assert client.app.state.blobs.read(blob.sha256) == '不可变材料'.encode()
    assert (target / 'workspaces/test/input/source.md').read_text(encoding='utf-8') == '保留全部材料'
    # Old process refuses new work until its managed owner switches the data root.
    assert client.post('/v1/conversations', json={'title': '不能继续写旧目录'}).status_code == 409
    app = create_app(AppSettings(target, 'qa-local-token', 'fake', False))
    with TestClient(app, headers={'Authorization': 'Bearer qa-local-token'}) as restarted:
        assert any(item['id'] == cid for item in restarted.get('/v1/conversations').json()['items'])
        assert app.state.blobs.read(blob.sha256) == '不可变材料'.encode()


def test_relocation_rejects_changed_source_nonempty_target_and_nested_paths(client, tmp_path):
    source = client.app.state.settings.data_root
    assert client.post('/v1/storage/relocation-preview', json={'destination': str(source / 'nested')}).status_code == 422
    target = tmp_path.parent / (tmp_path.name + '-target')
    target.mkdir()
    (target / 'keep.txt').write_text('不能覆盖')
    assert client.post('/v1/storage/relocation-preview', json={'destination': str(target)}).status_code == 409
    assert (target / 'keep.txt').read_text() == '不能覆盖'
    target2 = tmp_path.parent / (tmp_path.name + '-target2')
    plan = client.post('/v1/storage/relocation-preview', json={'destination': str(target2)}).json()
    client.post('/v1/conversations', json={'title': '预检后改变'})
    assert client.post('/v1/storage/relocate', json={'version': plan['version']}).status_code == 409
    assert client.post('/v1/conversations', json={'title': '迁移未开始，继续可写'}).status_code == 201


def test_relocation_blocks_unresolved_tasks(client, tmp_path):
    cid = client.post('/v1/conversations', json={'title': '待运行'}).json()['id']
    response = client.post(f'/v1/conversations/{cid}/turns', json={'text': '保持原文', 'client_request_id': 'request', 'provider_profile_id': 'fake-gpt'})
    assert response.status_code == 202
    target = tmp_path.parent / (tmp_path.name + '-new')
    plan = client.post('/v1/storage/relocation-preview', json={'destination': str(target)})
    assert plan.status_code == 409
    assert not target.exists()


def test_copy_failure_keeps_original_writable_and_does_not_claim_verified(client, tmp_path, monkeypatch):
    import app.storage.relocation as relocation
    source = client.app.state.settings.data_root
    client.app.state.blobs.put(b'keep source')
    target = tmp_path.parent / (tmp_path.name + '-disk-failure')
    plan = client.post('/v1/storage/relocation-preview', json={'destination': str(target)}).json()
    def fail(*args, **kwargs):
        raise OSError('simulated disk full')
    monkeypatch.setattr(relocation, 'copy_file', fail)
    response = client.post('/v1/storage/relocate', json={'version': plan['version']})
    assert response.status_code == 409
    assert source.is_dir()
    assert client.post('/v1/conversations', json={'title': '原目录继续可写'}).status_code == 201
    assert client.get('/v1/storage').json()['relocation_pending'] is False
