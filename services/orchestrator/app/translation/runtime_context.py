"""Durable language inputs for the real planning/workflow context gateway."""
from contextlib import closing
from dataclasses import asdict
import hashlib
import json
from uuid import uuid4

from app.runtime.context_gateway import ContextGateway, ValidatedEnglishView, ProtectedSpan
from app.runtime.state_machine import checkpoint_for
from app.storage.database import transaction
from .context_gateway import SourceMaterial, english_view
from .input_pipeline import InputPipeline
from .segments import segment_document
from .protection import protect

def _proof(value):
    data=dict(value); data['protected_spans']=tuple(ProtectedSpan(**v) for v in data.get('protected_spans',()))
    return ValidatedEnglishView(**data)

def load_gateway(service,workspace,task,attempt):
    route=service.router.lock(task,attempt)
    with closing(service.database.connect()) as connection:
        row=service.router.require_current(connection,route); context=checkpoint_for(row).get('language_context',{})
        if context.get('status')!='READY' or context.get('route_snapshot_id')!=route.id:
            raise ValueError('CLAUDE_INPUT_CONTEXT_NOT_READY')
        check=connection.execute("SELECT * FROM checks WHERE id=? AND task_id=? AND attempt_id=? AND check_kind='language.context' AND result='pass'",
            (context.get('validation_id'),task,attempt)).fetchone()
        if check is None or json.loads(check['details_json'])!=context:
            raise ValueError('CLAUDE_INPUT_CONTEXT_PROOF_MISSING')
        for job in context['job_ids']:
            found=connection.execute('SELECT status,route_snapshot_id,qa_id FROM translation_jobs WHERE id=? AND task_id=? AND attempt_id=?',(job,task,attempt)).fetchone()
            if not found or found['status']!='READY' or found['route_snapshot_id']!=route.id or not found['qa_id']:
                raise ValueError('CLAUDE_INPUT_JOB_NOT_READY')
        views={key:_proof(value) for key,value in context['english_views'].items()}
    return ContextGateway(workspace,views)

async def prepare_sources(service,workspace,task,attempt,sources,*,materials=(),composite=False):
    """Each original input stays authoritative; A receives only verified views.

    Composite planning views use already validated bilingual history (including
    the original approved English answers) and complete attachment views.
    """
    route=service.router.lock(task,attempt)
    context=await InputPipeline(service).prepare(task,attempt,workspace,materials=materials)
    if context.status!='READY': return context
    views=dict(context.english_views); jobs=list(context.job_ids)
    for source in sources:
        ref=source['ref']; raw=workspace.read('service',ref); digest=hashlib.sha256(raw).hexdigest()
        if digest!=source['sha256']: raise ValueError('LANGUAGE_CONTEXT_SOURCE_CHANGED')
        text=raw.decode('utf-8')
        if composite and ref not in views:
            # This is a deterministic assembly of independently verified full
            # user/history/material mappings, rather than another model pass.
            target=context.text.encode(); spans=[]; occupied=[]
            for segment in segment_document(text,locator=ref):
                if segment.kind=='gap': continue
                for span in protect(segment).spans:
                    wanted=span.raw.encode(); index=target.find(wanted)
                    while index>=0 and any(index<end and index+len(wanted)>start for start,end in occupied):
                        index=target.find(wanted,index+1)
                    if index<0: raise ValueError('COMPOSITE_PROTECTED_BYTES_MISSING')
                    start=len(text[:segment.source_start+span.start].encode())
                    spans.append(ProtectedSpan(start,start+len(wanted),index,index+len(wanted)))
                    occupied.append((index,index+len(wanted)))
            view_ref='translation/context-'+uuid4().hex+'.en.md'; workspace.write('service',view_ref,target)
            views[ref]=ValidatedEnglishView(ref,digest,view_ref,hashlib.sha256(target).hexdigest(),
                'composite:'+route.id,coverage_passed=True,protected_spans_passed=True,numeric_entities_passed=True,protected_spans=tuple(spans))
        elif ref not in views:
            value=await service.translate(task_id=task,attempt_id=attempt,source=text,source_language='mul',
                target_language='en',purpose='runtime-source',source_locator=ref)
            jobs.append(value.job_id)
            if value.status!='READY':
                from .input_pipeline import InputContext
                return InputContext(value.status,'',tuple(jobs),clarification=value.clarification)
            views[ref]=english_view(workspace,SourceMaterial(ref),value)[0]
    gateway=ContextGateway(workspace,views)
    for source in sources: gateway.read('claude',source['ref'])
    proof=dict(status='READY',route_snapshot_id=route.id,validation_id='language-context-'+uuid4().hex,
        job_ids=jobs,english_views={key:asdict(value) for key,value in views.items()},
        full_scope=list(context.full_scope),read_scope=list(context.read_scope),sources=list(sources))
    with closing(service.database.connect()) as connection,transaction(connection):
        row=service.router.require_current(connection,route); checkpoint=checkpoint_for(row)
        checkpoint['language_context']=proof
        connection.execute('UPDATE task_runs SET checkpoint_json=? WHERE task_id=? AND attempt_id=?',(json.dumps(checkpoint),task,attempt))
        connection.execute("INSERT INTO checks(id,task_id,attempt_id,check_kind,result,check_version,details_json) VALUES(?,?,?,'language.context','pass','1.0',?)",
            (proof['validation_id'],task,attempt,json.dumps(proof)))
    return context
