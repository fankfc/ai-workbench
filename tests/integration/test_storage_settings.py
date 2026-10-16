def test_cleanup_preview_only_offers_unreferenced_blobs_and_is_fenced(client):
    store = client.app.state.blobs
    orphan = store.put(b'private orphan')
    preview = client.post('/v1/storage/cleanup-preview')
    assert preview.status_code == 200
    plan = preview.json()
    assert orphan.sha256 in [x['sha256'] for x in plan['items']]
    store.put(b'a later blob makes the preview stale')
    response = client.post('/v1/storage/cleanup', json={'version': plan['version'], 'sha256s': [orphan.sha256]})
    assert response.status_code == 409
    assert store.read(orphan.sha256) == b'private orphan'
    plan = client.post('/v1/storage/cleanup-preview').json()
    response = client.post('/v1/storage/cleanup', json={'version': plan['version'], 'sha256s': [orphan.sha256]})
    assert response.status_code == 200
    assert response.json()['removed'] == [orphan.sha256]
    assert not store.path_for(orphan.sha256).exists()


def test_storage_does_not_expose_paths_or_allow_traversal(client):
    assert client.get('/v1/storage').status_code == 200
    assert str(client.app.state.settings.data_root) not in client.get('/v1/storage').text
    response = client.post('/v1/storage/cleanup', json={'version': 'x', 'sha256s': ['../workbench.sqlite3']})
    assert response.status_code == 422
