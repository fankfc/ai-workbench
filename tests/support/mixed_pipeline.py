"""Fixed test-only CSV -> native analysis -> JSON -> SVG -> immutable DAG.

The helper prepares mechanical fixture evidence. It never substitutes a provider,
claims model authorship, enables a production renderer or publishes an answer.
"""
from contextlib import closing
import csv
from decimal import Decimal,InvalidOperation
import hashlib
import io
import json
from pathlib import Path
import sys
from uuid import uuid4
import xml.etree.ElementTree as ET

from app.contracts.artifacts import ArtifactVersion
from app.storage.blobs import read_artifact,store_artifact
from app.storage.database import Database,transaction
from app.storage.revisions import activate_revision
from app.validation.base import ArtifactSnapshot,ValidationContext
from app.validation.registry import Registry

DATA=b'value\n1\n2\n3\n'
ANALYSIS=b'''from pathlib import Path
import csv,hashlib,json,sys
from decimal import Decimal
import xml.etree.ElementTree as ET
source=Path(sys.argv[1])
destination=Path(sys.argv[2])
destination.mkdir(parents=True,exist_ok=True)
raw=source.read_bytes()
values=[Decimal(row['value']) for row in csv.DictReader(raw.decode('utf-8').splitlines())]
assert len(values)==3 and all(value.is_finite() for value in values)
total=sum(values,Decimal(0))
result={'sum':int(total),'count':len(values),'source_sha256':hashlib.sha256(raw).hexdigest()}
result_bytes=(json.dumps(result,sort_keys=True)+'\\n').encode('utf-8')
(destination/'result.json').write_bytes(result_bytes)
svg=ET.Element('svg',xmlns='http://www.w3.org/2000/svg',width='320',height='200',viewBox='0 0 320 200')
ET.SubElement(svg,'metadata').text=json.dumps({'test_only':True,'source_sha256':hashlib.sha256(raw).hexdigest(),'result_sha256':hashlib.sha256(result_bytes).hexdigest()},sort_keys=True)
ET.SubElement(svg,'text',x='12',y='20').text='Fixed fixture sum='+str(total)
for index,value in enumerate(values):
    height=float(value*40)
    ET.SubElement(svg,'rect',x=str(35+index*85),y=str(165-height),width='45',height=str(height),fill='#235789',**{'data-value':str(value)})
    ET.SubElement(svg,'text',x=str(45+index*85),y='185').text=str(value)
(destination/'figure.svg').write_bytes(ET.tostring(svg,encoding='utf-8',xml_declaration=True))
print(str(total))
'''


def prepare_mixed(database_path,store,workspace,runner):
    """Create fixed upstream versions for a subsequent real Workflow candidate."""
    database=Database(Path(database_path))
    task_id,attempt_id=workspace.root.parent.name,workspace.root.name
    with closing(database.connect()) as connection:
        if connection.execute('SELECT 1 FROM task_runs WHERE task_id=? AND attempt_id=?',(task_id,attempt_id)).fetchone() is None:
            raise ValueError('MIXED_WORKSPACE_ATTEMPT_BINDING_REQUIRED')
    data_path=workspace.ingest_source('md.csv',DATA)
    analysis_path=workspace.ingest_source('mx.py',ANALYSIS)
    revision_ids={logical:'mx-'+logical+'-'+uuid4().hex for logical in ('data','analysis','result','figure')}

    def register(logical,data,dependencies):
        sha=hashlib.sha256(data).hexdigest()
        artifact=ArtifactVersion(id=revision_ids[logical],task_id=task_id,artifact_kind=logical,language='en',immutable_uri=store.uri_for(sha),byte_sha256=sha,canonical_content_sha256=sha,source_version_id=None,origin_authors=['fixture-service'],canonical_issued_by='fixture-service',reviewed_by=[],rendered_by='fixed-analysis-fixture',a_response_ref=None,dependencies=[dict(artifact_version_id=revision_ids[parent],relationship='derived_from') for parent in dependencies])
        with closing(database.connect()) as connection:
            store_artifact(connection,store,data,artifact,attempt_id=attempt_id,provenance={'test_only':True,'source_role':'fixed-mechanical-fixture','fixed_analysis_sha256':hashlib.sha256(ANALYSIS).hexdigest()})
            activate_revision(connection,store,task_id,attempt_id,logical,artifact.id,{parent:revision_ids[parent] for parent in dependencies})
        return sha

    data_sha=register('data',workspace.read('A','input/md.csv'),())
    analysis_sha=register('analysis',workspace.read('A','input/mx.py'),('data',))
    workspace.write('service','artifacts/mx/.fixture',b'test_only fixed analysis\n')
    command=[sys.executable,'input/mx.py','input/md.csv','artifacts/mx']
    criterion=dict(id='mixed-analysis-execution',mandatory=True,verifier='C',evidence_type='execution',condition='Run the exact fixed analysis against the immutable fixture CSV',semantic=False)
    with closing(database.connect()) as connection:
        context=ValidationContext(task_id,attempt_id,ArtifactSnapshot(revision_ids['analysis'],analysis_sha,analysis_path),[criterion],workspace.root,source=ArtifactSnapshot(revision_ids['data'],data_sha,data_path),runner=runner,commands={criterion['id']:command},connection=connection,store=store,environment={'test_only':True,'fixture_trust':'fixed-script-sha256','analysis_sha256':analysis_sha},execution_authorized=analysis_sha==hashlib.sha256(ANALYSIS).hexdigest())
        results=Registry().validate('code',context)
        for result in results:
            with transaction(connection):
                connection.execute("INSERT INTO checks(id,task_id,attempt_id,artifact_version_id,check_kind,result,check_version,evidence_ref,details_json) VALUES(?,?,?,?,?,?,?,?,?)",('mx-check-'+uuid4().hex,task_id,attempt_id,revision_ids['analysis'],'fixture.mixed.analysis',result.status,result.validator_version,str(workspace.root/result.evidence_ref) if result.evidence_ref else None,json.dumps({**result.to_dict(),'test_only':True})))
    if len(results)!=1 or results[0].status!='pass':
        raise ValueError('MIXED_ANALYSIS_CHECK_FAILED')
    result_path=workspace.resolve('artifacts/mx/result.json',role='service')
    figure_path=workspace.resolve('artifacts/mx/figure.svg',role='service')
    if not result_path.is_file() or not figure_path.is_file():
        raise ValueError('MIXED_ANALYSIS_OUTPUT_MISSING')
    result_bytes=workspace.read('A','artifacts/mx/result.json')
    figure_bytes=workspace.read('A','artifacts/mx/figure.svg')
    try:
        result_data=json.loads(result_bytes)
        svg=ET.fromstring(figure_bytes)
        if not isinstance(result_data,dict) or 'sum' not in result_data or svg.tag!='{http://www.w3.org/2000/svg}svg' or len(svg.findall('{http://www.w3.org/2000/svg}rect'))!=3:
            raise ValueError('MIXED_ANALYSIS_OUTPUT_INVALID')
    except (ValueError,ET.ParseError):
        raise ValueError('MIXED_ANALYSIS_OUTPUT_INVALID') from None
    actual_source=workspace.read('A','input/md.csv')
    values=[Decimal(row['value']) for row in csv.DictReader(io.StringIO(actual_source.decode('utf-8')))]
    total=sum(values,Decimal(0))
    if type(result_data.get('sum')) is not int or result_data['sum']!=total or type(result_data.get('count')) is not int or result_data['count']!=len(values) or result_data.get('source_sha256')!=data_sha:
        raise ValueError('MIXED_RESULT_DATA_MISMATCH')
    try:
        metadata=svg.find('{http://www.w3.org/2000/svg}metadata')
        binding=json.loads(metadata.text) if metadata is not None else {}
        bars=svg.findall('{http://www.w3.org/2000/svg}rect')
        matching=binding.get('test_only') is True and binding.get('source_sha256')==data_sha and binding.get('result_sha256')==hashlib.sha256(result_bytes).hexdigest()
        matching=matching and all(Decimal(bar.get('data-value','NaN'))==value and Decimal(bar.get('height','NaN'))==value*40 for bar,value in zip(bars,values,strict=True))
    except (ValueError,InvalidOperation):
        matching=False
    if not matching:
        raise ValueError('MIXED_FIGURE_DATA_MISMATCH')
    result_sha=register('result',result_bytes,('analysis',))
    figure_sha=register('figure',figure_bytes,('result',))
    # The exact produced bytes become immutable source context for the final A/B
    # fixture report. The original output and each content-addressed blob remain.
    workspace.ingest_source('mr.json',result_bytes)
    workspace.ingest_source('mf.svg',figure_bytes)
    source_inputs=[dict(id='mixed-data',ref='input/md.csv',sha256=data_sha),dict(id='mixed-analysis',ref='input/mx.py',sha256=analysis_sha),dict(id='mixed-result',ref='input/mr.json',sha256=result_sha),dict(id='mixed-figure',ref='input/mf.svg',sha256=figure_sha)]
    return dict(dependency_revision_ids=[revision_ids['result'],revision_ids['figure']],source_inputs=source_inputs,validator_results=[value.to_dict() for value in results],revision_ids=revision_ids)
