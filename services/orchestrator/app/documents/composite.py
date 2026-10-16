"""Scoped reproducible monthly analysis, independently checked report bindings.

The local runner executes only the service's fixed, hash-checked analysis
program. Arbitrary model-provided programs require a separately qualified
execution port; an ordinary Windows directory is not an OS sandbox.
"""
from contextlib import closing
import csv
from decimal import Decimal
import io
import json
from pathlib import Path
import re
import subprocess
import sys
from uuid import uuid4

from app.contracts.artifacts import ArtifactVersion, ArtifactDependency
from app.storage.blobs import BlobStore, store_artifact, read_artifact
from app.storage.database import Database
from app.storage.revisions import activate_revision, is_current_revision
from .model import digest, json_bytes


ANALYSIS_CODE = b'''import csv, json, sys
from decimal import Decimal
from pathlib import Path
source = Path(sys.argv[1]).read_bytes()
rows = list(csv.DictReader(source.decode("utf-8").splitlines()))
totals = {}
for row in rows:
    month = row["month"]
    totals[month] = totals.get(month, Decimal(0)) + Decimal(row["amount"])
months = sorted(totals)
if len(rows) != 4 or len(months) != 2:
    raise ValueError("FOUR_ROWS_TWO_MONTHS_REQUIRED")
result = {"rows": len(rows), "monthly_totals": {m: str(totals[m]) for m in months},
          "increase": str(totals[months[1]] - totals[months[0]])}
print(json.dumps(result, sort_keys=True))
'''


def _independent_totals(data):
    rows=list(csv.DictReader(io.StringIO(data.decode('utf-8'))))
    if len(rows)!=4 or any(set(r)!={'month','category','amount'} for r in rows): raise ValueError('CSV_REQUIRED_ROWS_OR_COLUMNS_MISSING')
    totals={}
    for row in rows:
        if re.fullmatch(r'\d{4}-\d{2}',row['month']) is None or row['category'] not in ('A','B'):
            raise ValueError('CSV_DOMAIN_INVALID')
        value=Decimal(row['amount'])
        if not value.is_finite() or value<0: raise ValueError('CSV_AMOUNT_INVALID')
        totals[row['month']]=totals.get(row['month'],Decimal(0))+value
    months=sorted(totals)
    if len(months)!=2 or len({(r['month'],r['category']) for r in rows})!=4: raise ValueError('CSV_OBSERVATIONS_INCOMPLETE')
    if months[0][-2:]!='01' or months[1][-2:]!='02' or months[0][:4]!=months[1][:4]:
        raise ValueError('CSV_MONTH_LABELS_UNSUPPORTED')
    return {'rows':len(rows),'monthly_totals':{m:str(totals[m]) for m in months},'increase':str(totals[months[1]]-totals[months[0]])}


def _chart(results):
    from reportlab.pdfgen.canvas import Canvas
    import pymupdf
    stream=io.BytesIO(); canvas=Canvas(stream,pagesize=(620,400))
    canvas.setTitle('Monthly totals'); canvas.setFont('Helvetica',14); canvas.drawString(52,360,'Monthly totals')
    canvas.setStrokeColorRGB(.2,.2,.2); canvas.line(60,70,570,70); canvas.line(60,70,60,330)
    values=list(results['monthly_totals'].items()); highest=max(Decimal(v) for _,v in values)
    for index,(month,value) in enumerate(values):
        height=float(Decimal(value)/highest)*220 if highest else 0; x=140+index*220
        canvas.setFillColorRGB(.18,.4,.66); canvas.rect(x,70,90,height,fill=1,stroke=0)
        canvas.setFillColorRGB(.1,.1,.1); canvas.setFont('Helvetica',12); canvas.drawCentredString(x+45,46,month)
        canvas.drawCentredString(x+45,84+height,value)
    canvas.save()
    with pymupdf.open(stream=stream.getvalue(),filetype='pdf') as pdf:
        return pdf[0].get_pixmap(matrix=pymupdf.Matrix(1.5,1.5)).tobytes('png')


class CompositePipeline:
    def __init__(self,database_path,workspace_manager):
        self.database=Database(database_path); self.store=BlobStore(self.database.path.parent/'blobs'); self.workspaces=workspace_manager

    def _save(self,task,attempt,data,kind,logical,dependencies,provenance):
        sha=digest(data); aid=logical+'-'+uuid4().hex
        artifact=ArtifactVersion(id=aid,task_id=task,artifact_kind=kind,language='und',immutable_uri=self.store.uri_for(sha),byte_sha256=sha,
            canonical_content_sha256=sha,source_version_id=None,origin_authors=['C'],canonical_issued_by='C',reviewed_by=[],rendered_by='C',a_response_ref=None,
            dependencies=[ArtifactDependency(artifact_version_id=v,relationship='computed_from') for v in dependencies.values()])
        with closing(self.database.connect()) as c:
            store_artifact(c,self.store,data,artifact,attempt_id=attempt,provenance=provenance)
            activate_revision(c,self.store,task,attempt,logical,aid,dependencies)
        return aid

    def run(self,task_id,attempt_id,data,*,code=ANALYSIS_CODE,fail_chart=False):
        if not isinstance(data,bytes) or len(data)>1_000_000: raise ValueError('CSV_SIZE_INVALID')
        if not isinstance(code,bytes) or digest(code)!=digest(ANALYSIS_CODE): raise ValueError('QUALIFIED_EXECUTION_PORT_REQUIRED')
        expected=_independent_totals(data)
        workspace=self.workspaces.create(task_id,attempt_id); version='analysis-'+uuid4().hex
        workspace.ingest_source(version+'.csv',data); workspace.ingest_source(version+'.py',code)
        csv_path=workspace.resolve('input/'+version+'.csv','service')
        code_path=workspace.resolve('input/'+version+'.py','service')
        result=subprocess.run([sys.executable,str(code_path),str(csv_path)],cwd=workspace.root,capture_output=True,text=True,
            encoding='utf-8',timeout=15,check=False)
        if result.returncode: raise ValueError('ANALYSIS_EXECUTION_FAILED')
        observed=json.loads(result.stdout)
        if observed!=expected: raise ValueError('ANALYSIS_INDEPENDENT_RECOMPUTATION_MISMATCH')
        source=self._save(task_id,attempt_id,data,'csv','source_data',{}, {'source_sha256':digest(data)})
        analysis=self._save(task_id,attempt_id,code,'python','analysis_code',{'source_data':source},{'code_sha256':digest(code)})
        computed=self._save(task_id,attempt_id,json_bytes(observed),'json','computed_results',{'analysis_code':analysis,'source_data':source},
            {'source_sha256':digest(data),'code_sha256':digest(code),'command_exit_code':result.returncode,'independent_results':expected})
        if fail_chart: raise ValueError('CHART_GENERATION_FAILED')
        chart=self._save(task_id,attempt_id,_chart(observed),'png','figures',{'computed_results':computed},
            {'computed_results_sha256':digest(json_bytes(observed)),'source_sha256':digest(data),'code_sha256':digest(code)})
        return {'source_data':source,'analysis_code':analysis,'computed_results':computed,'figures':chart,'results':observed,
            'source_ref':'input/'+version+'.csv','code_ref':'input/'+version+'.py','source_sha256':digest(data),'code_sha256':digest(code),
            'command':[sys.executable,'<scoped-analysis.py>','<scoped-sales.csv>'],'exit_code':result.returncode}

    def validator(self,run):
        def validate(candidate):
            with closing(self.database.connect()) as c:
                current=all(is_current_revision(c,candidate.contract.task_id,candidate.contract.attempt_id,run[k]) for k in ('source_data','analysis_code','computed_results','figures'))
                source=read_artifact(c,self.store,run['source_data']); results=json.loads(read_artifact(c,self.store,run['computed_results']))
                read_artifact(c,self.store,run['figures'])
                recomputed=_independent_totals(source)
            expected=[*recomputed['monthly_totals'].values(),recomputed['increase']]
            content=candidate.content.decode('utf-8')
            labels=['January','February','Increase']
            bindings={label:re.findall(r'\b'+label+r'\s+(?:total\s+)?(-?\d+(?:\.\d+)?)',content,re.I) for label in labels}
            # Values elsewhere in the report cannot repair a stale conclusion.
            # Bind each reported field to its independently recomputed value.
            present=all(bindings[label] and all(Decimal(value)==Decimal(expected[index]) for value in bindings[label])
                for index,label in enumerate(labels))
            passed=current and results==recomputed and present
            return [dict(criterion_id=criterion.id,passed=passed,evidence={'source_sha256':digest(source),
                'computed_results':results,'independent_results':recomputed,'report_sha256':candidate.byte_sha256,
                'report_required_values':expected,'report_field_bindings':bindings,'current_dependencies':current,'report_values_present':bool(present)})
                for criterion in candidate.contract.acceptance if not criterion.semantic]
        return validate
