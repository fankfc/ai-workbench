import asyncio
import pytest
from app.runtime.workspace import WorkspaceManager
from app.runtime.context_gateway import ContextGateway
from app.translation.input_pipeline import InputPipeline
from app.translation.context_gateway import SourceMaterial
from app.translation.segments import UnsupportedSyntax
from translation.fakes import service,claude_turn

def test_two_round_history_preserves_first_prohibition_without_backtranslation(client):
    conversation,task,attempt=claude_turn(client,'禁止删除原始文件。')
    workspaces=WorkspaceManager(client.app.state.settings.data_root)
    translation=service(client); pipeline=InputPipeline(translation)
    first=asyncio.run(pipeline.prepare(task,attempt,workspaces.create(task,attempt)))
    assert first.status=='READY' and 'Do not delete original files.' in first.text
    _,next_task,next_attempt=claude_turn(client,'只增加 PDF。',conversation,'two')
    second=asyncio.run(pipeline.prepare(next_task,next_attempt,workspaces.create(next_task,next_attempt)))
    assert second.status=='READY' and 'Do not delete original files.' in second.text and 'Only add PDF.' in second.text
    assert len(translation.translator.calls)==2

def test_scoped_markdown_material_uses_runtime_gateway_and_keeps_original(client):
    _,task,attempt=claude_turn(client)
    workspace=WorkspaceManager(client.app.state.settings.data_root).create(task,attempt)
    raw='保留原文件。 `print("中文界面")` -0.03'
    workspace.ingest_source('material.md',raw.encode())
    translation=service(client)
    result=asyncio.run(InputPipeline(translation).prepare(task,attempt,workspace,materials=[SourceMaterial('input/material.md')]))
    assert result.status=='READY' and result.full_scope[0]['coverage']=='full'
    content=ContextGateway(workspace,result.english_views).read('claude','input/material.md').content.decode()
    assert 'Keep the original file.' in content and '`print("中文界面")`' in content
    assert workspace.read('service','input/material.md').decode()==raw

def test_critical_ocr_ambiguity_and_unsupported_pdf_never_prepare_a_context(client):
    _,task,attempt=claude_turn(client); workspace=WorkspaceManager(client.app.state.settings.data_root).create(task,attempt)
    workspace.ingest_source('scan.txt',b'1/7')
    translation=service(client); pipeline=InputPipeline(translation)
    unclear=asyncio.run(pipeline.prepare(task,attempt,workspace,materials=[SourceMaterial('input/scan.txt',critical_ocr_uncertainty=True)]))
    assert unclear.status=='NEEDS_INPUT' and unclear.text==''
    with pytest.raises(UnsupportedSyntax,match='FORMAT_UNAVAILABLE'):
        asyncio.run(pipeline.prepare(task,attempt,workspace,materials=[SourceMaterial('input/scan.txt',format='pdf')]))

def test_input_coverage_failure_returns_no_a_request_text(client):
    _,task,attempt=claude_turn(client,'一段。\n\n二段。'); workspace=WorkspaceManager(client.app.state.settings.data_root).create(task,attempt)
    result=asyncio.run(InputPipeline(service(client,transform=lambda r:{})).prepare(task,attempt,workspace))
    assert result.status=='FAILED' and result.text==''

def test_native_material_is_kept_in_full_input_scope_without_translation(client):
    from contextlib import closing
    with closing(client.app.state.database.connect()) as connection:
        connection.execute("UPDATE provider_profiles SET identity_status='verified',identity_source='fixture:fake' WHERE id='fake-gpt'")
    conversation=client.post('/v1/conversations',json={'title':'native materials'}).json()['id']
    task=client.post(f'/v1/conversations/{conversation}/turns',json={'text':'保留原文件。','provider_profile_id':'fake-gpt','client_request_id':'native'}).json()['task_id']
    with closing(client.app.state.database.connect()) as connection: attempt=connection.execute('SELECT attempt_id FROM task_runs WHERE task_id=?',(task,)).fetchone()[0]
    workspace=WorkspaceManager(client.app.state.settings.data_root).create(task,attempt)
    workspace.ingest_source('log.md','禁止删除原始文件。'.encode()); translation=service(client)
    result=asyncio.run(InputPipeline(translation).prepare(task,attempt,workspace,materials=[SourceMaterial('input/log.md')]))
    assert result.status=='READY' and '禁止删除原始文件。' in result.text
    assert result.full_scope[0]['coverage']=='full' and not translation.translator.calls

def test_switch_from_gpt_to_claude_builds_english_history_from_original_chinese(client):
    from contextlib import closing
    with closing(client.app.state.database.connect()) as connection:
        connection.execute("UPDATE provider_profiles SET identity_status='verified',identity_source='fixture:fake' WHERE id='fake-gpt'")
    conversation=client.post('/v1/conversations',json={'title':'switch language'}).json()['id']
    task=client.post(f'/v1/conversations/{conversation}/turns',json={'text':'禁止删除原始文件。','provider_profile_id':'fake-gpt','client_request_id':'native'}).json()['task_id']
    with closing(client.app.state.database.connect()) as connection: attempt=connection.execute('SELECT attempt_id FROM task_runs WHERE task_id=?',(task,)).fetchone()[0]
    workspaces=WorkspaceManager(client.app.state.settings.data_root); translation=service(client); pipeline=InputPipeline(translation)
    first=asyncio.run(pipeline.prepare(task,attempt,workspaces.create(task,attempt)))
    assert first.status=='READY' and not translation.translator.calls
    _,next_task,next_attempt=claude_turn(client,'只增加 PDF。',conversation,'claude')
    next_context=asyncio.run(pipeline.prepare(next_task,next_attempt,workspaces.create(next_task,next_attempt)))
    assert next_context.status=='READY' and 'Do not delete original files.' in next_context.text and 'Only add PDF.' in next_context.text
