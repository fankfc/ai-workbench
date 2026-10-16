from urllib.parse import quote


def test_upload_references_are_scoped_and_bytes_are_immutable(client):
    first = client.post('/v1/conversations', json={'title': '一'}).json()['id']
    second = client.post('/v1/conversations', json={'title': '二'}).json()['id']
    uploaded = client.post(f'/v1/conversations/{first}/attachments', content='不删除文件'.encode(),
        headers={'Content-Type': 'application/octet-stream', 'X-Filename': quote('需求.md')})
    assert uploaded.status_code == 201
    item = uploaded.json()
    assert item['name'] == '需求.md' and item['status'] == 'ready'
    assert client.app.state.blobs.read(item['sha256']).decode() == '不删除文件'
    assert client.get(f'/v1/conversations/{second}/attachments').json()['items'] == []
    body = {'text': '查阅', 'provider_profile_id': 'fake-gpt', 'client_request_id': 'r', 'attachment_ids': [item['id']]}
    assert client.post(f'/v1/conversations/{second}/turns', json=body).status_code == 409
    response = client.post(f'/v1/conversations/{first}/turns', json=body)
    assert response.status_code == 202
    assert client.post(f'/v1/conversations/{first}/turns', json=body).json() == response.json()
    assert client.delete(f'/v1/conversations/{first}/attachments/{item["id"]}').status_code == 409


def test_unsupported_and_malicious_uploads_are_rejected(client):
    cid = client.post('/v1/conversations', json={'title': '测试'}).json()['id']
    path = f'/v1/conversations/{cid}/attachments'
    for name in ('../data.md', 'C:\\secret.md', 'script.exe'):
        assert client.post(path, content=b'x', headers={'Content-Type': 'application/octet-stream', 'X-Filename': quote(name)}).status_code == 422
    assert client.post(path, content=b'\xff', headers={'Content-Type': 'application/octet-stream', 'X-Filename': 'a.md'}).status_code == 422
