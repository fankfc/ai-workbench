"""Service-authored fixed analysis executed through the actual native runner."""
from contextlib import closing
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET

import pytest

from app.runtime.processes import ProcessManager
from app.runtime.workspace import WorkspaceManager
from app.validation.base import CommandResult,NativeMechanicalRunner
from app.storage.blobs import read_artifact
from app.storage.revisions import is_current_revision
from support.mixed_pipeline import prepare_mixed


def task(client):
    conversation=client.post('/v1/conversations',json={'title':'mixed helper'}).json()['id']
    accepted=client.post(f'/v1/conversations/{conversation}/turns',json={'text':'固定综合夹具','provider_profile_id':'fake-gpt','client_request_id':'mixed'}).json()
    database=client.app.state.database
    with closing(database.connect()) as connection:
        row=connection.execute('SELECT * FROM task_runs WHERE task_id=?',(accepted['task_id'],)).fetchone()
        identifiers=row['task_id'],row['attempt_id']
    workspace=WorkspaceManager(database.path.parent).create(*identifiers)
    return database,workspace,identifiers


@pytest.mark.windows
def test_prepare_mixed_produces_real_outputs_and_explicit_dag(client):
    database,workspace,identifiers=task(client)
    with ProcessManager(database.path.parent/'mixed-processes.sqlite3') as manager:
        value=prepare_mixed(database.path,client.app.state.blobs,workspace,NativeMechanicalRunner(manager,*identifiers))
    assert set(value['revision_ids'])=={'data','analysis','result','figure'}
    assert value['dependency_revision_ids']==[value['revision_ids']['result'],value['revision_ids']['figure']]
    for source in value['source_inputs']:
        data=workspace.read('A',source['ref'])
        assert hashlib.sha256(data).hexdigest()==source['sha256']
    with closing(database.connect()) as connection:
        result_bytes=read_artifact(connection,client.app.state.blobs,value['revision_ids']['result'])
        figure_bytes=read_artifact(connection,client.app.state.blobs,value['revision_ids']['figure'])
        assert json.loads(result_bytes)['sum']==6
        svg=ET.fromstring(figure_bytes)
        assert svg.tag=='{http://www.w3.org/2000/svg}svg'
        assert len(svg.findall('{http://www.w3.org/2000/svg}rect'))==3
        expected={'analysis':[value['revision_ids']['data']],'result':[value['revision_ids']['analysis']],'figure':[value['revision_ids']['result']]}
        for logical,revision in value['revision_ids'].items():
            row=connection.execute('SELECT * FROM artifact_revisions WHERE id=?',(revision,)).fetchone()
            assert [item['artifact_version_id'] for item in json.loads(row['dependencies_json'])]==expected.get(logical,[])
            assert is_current_revision(connection,*identifiers,revision)
            assert json.loads(row['provenance_json'])['test_only'] is True
        assert connection.execute("SELECT count(*) FROM checks WHERE task_id=? AND check_kind='fixture.mixed.analysis'",(identifiers[0],)).fetchone()[0]==1
    proof=value['validator_results'][0]
    assert proof['status']=='pass' and proof['method']=='native_code_execution'
    evidence=json.loads((workspace.root/proof['evidence_ref']).read_text(encoding='utf-8'))
    assert evidence['details']['executed'] is True and evidence['details']['exit_code']==0


def test_noop_analysis_cannot_register_fake_result_or_figure(client):
    database,workspace,identifiers=task(client)
    with pytest.raises(ValueError,match='MIXED_ANALYSIS_OUTPUT_MISSING'):
        prepare_mixed(database.path,client.app.state.blobs,workspace,lambda *args:CommandResult(0,b'6\n',b''))
    with closing(database.connect()) as connection:
        kinds={row[0] for row in connection.execute('SELECT artifact_kind FROM artifact_revisions WHERE task_id=?',(identifiers[0],))}
    assert 'figure' not in kinds and 'result' not in kinds


def test_unexecuted_analysis_never_qualifies_outputs(client):
    database,workspace,_=task(client)
    with pytest.raises(ValueError,match='MIXED_ANALYSIS_CHECK_FAILED'):
        prepare_mixed(database.path,client.app.state.blobs,workspace,lambda *args:CommandResult(0,b'6\n',b'',executed=False))


def writes_wrong_outputs(argv,cwd,timeout,*,wrong_sum=False,wrong_figure=False):
    root=Path(cwd)
    raw=(root/argv[2]).read_bytes()
    output=root/argv[3]
    output.mkdir(parents=True,exist_ok=True)
    result=json.dumps({'sum':5 if wrong_sum else 6,'count':3,'source_sha256':hashlib.sha256(raw).hexdigest()}).encode()
    (output/'result.json').write_bytes(result)
    svg=ET.Element('svg',xmlns='http://www.w3.org/2000/svg')
    ET.SubElement(svg,'metadata').text=json.dumps({'test_only':True,'source_sha256':hashlib.sha256(raw).hexdigest(),'result_sha256':hashlib.sha256(result).hexdigest()})
    for value in (1,2,3):
        ET.SubElement(svg,'rect',height=str(5 if wrong_figure else value*40),**{'data-value':str(value)})
    (output/'figure.svg').write_bytes(ET.tostring(svg))
    return CommandResult(0,b'6\n',b'')


def test_result_bytes_must_recompute_to_actual_input_values(client):
    database,workspace,_=task(client)
    with pytest.raises(ValueError,match='MIXED_RESULT_DATA_MISMATCH'):
        prepare_mixed(database.path,client.app.state.blobs,workspace,lambda *args:writes_wrong_outputs(*args,wrong_sum=True))


def test_svg_bar_values_and_result_hash_must_match_actual_sources(client):
    database,workspace,_=task(client)
    with pytest.raises(ValueError,match='MIXED_FIGURE_DATA_MISMATCH'):
        prepare_mixed(database.path,client.app.state.blobs,workspace,lambda *args:writes_wrong_outputs(*args,wrong_figure=True))
