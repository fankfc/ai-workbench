"""Persistent translation jobs: full coverage, separate QA, bounded repairs."""
from contextlib import closing
from dataclasses import dataclass, replace
from copy import deepcopy
import hashlib
import json
from uuid import uuid4

from app.contracts.translation import SemanticFinding, TranslationJob, TranslationQA
from app.contracts.providers import ProviderContract
from app.storage.database import Database, transaction
from app.storage.blobs import BlobStore
from app.usage.ledger import UsageLedger
from .router import LanguageRouter
from .segments import segment_document, Segment
from .protection import protect
from .quality import evaluate, high_impact
from .cache import cache_key
from .glossary import GlossaryStore
from .ports import TranslationRequest, TranslationResponse, PortUnavailable
from app.runtime.role_prompts import load_role_prompt


@dataclass(frozen=True)
class TranslationResult:
    job_id: str
    status: str
    text: str | None
    source_sha256: str
    target_sha256: str | None
    qa_id: str | None
    candidate_attempts: int
    cache_hit: bool=False
    clarification: str | None=None
    blocks: tuple[dict,...]=()


class TranslationService:
    def __init__(self,database_path,translator,checker,*,policy_version='translation:1.0',max_b_tokens=None):
        if translator is checker:
            raise ValueError('SEPARATE_SEMANTIC_CHECK_PORT_REQUIRED')
        self.database_path=database_path; self.database=Database(database_path)
        self.store=BlobStore(self.database.path.parent/'blobs'); self.router=LanguageRouter(database_path)
        self.translator=translator; self.checker=checker; self.policy_version=policy_version
        self.max_b_tokens=max_b_tokens
        if max_b_tokens is not None and (type(max_b_tokens) is not int or max_b_tokens<0):
            raise ValueError('INVALID_TRANSLATION_BUDGET')
        for port in (translator,checker):
            port.identity.require_executable()
            if port.identity.identity.family!='glm': raise ValueError('B_TRANSLATION_GLM_IDENTITY_REQUIRED')

    def _response_json(self,response):
        return dict(blocks=response.blocks,findings=list(response.findings),complete=response.complete,
            usage=response.usage,identity=response.identity.model_dump(mode='json') if response.identity else None)

    def _decode_response(self,data):
        return TranslationResponse(blocks=data.get('blocks',{}),findings=tuple(data.get('findings',())),
            complete=data.get('complete',False),usage=data.get('usage'),identity=ProviderContract.model_validate(data['identity']) if data.get('identity') else None)

    def _validated_findings(self,response,request):
        try:
            if not isinstance(response.findings,(tuple,list)):
                raise ValueError('finding list required')
            scope={block['block_id']:block['source_locator'] for block in request.blocks}
            findings=tuple(SemanticFinding.model_validate(item) for item in response.findings)
            if any(finding.block_id not in scope or finding.source_locator!=scope[finding.block_id] for finding in findings):
                raise ValueError('finding source binding required')
            return tuple(finding.model_dump(mode='json') for finding in findings)
        except (ValueError,TypeError):
            raise PortUnavailable('B_TRANSLATION_FINDINGS_INVALID') from None

    def _record_usage(self,job,request,port,response,status='completed'):
        raw=response.usage or {'usage_observed':False}
        UsageLedger(self.database_path).record(task_id=job['task_id'],attempt_id=job['attempt_id'],
            provider_profile_id=port.identity.provider_id,external_request_id=request.request_id,
            event_id=request.request_id+':usage',provider='glm',raw=raw,
            source='reported' if response.usage is not None else 'unknown',mode='request_total',sequence=1,
            role='B',function='translation',domain='mixed',status=status)

    async def _call(self,job,request,port,route):
        for connection_attempt in range(1,4):
            bound=TranslationRequest(**{**request.__dict__,'request_id':f'{request.request_id}:connection:{connection_attempt}'})
            with closing(self.database.connect()) as connection,transaction(connection):
                self.router.require_current(connection,route)
                saved=connection.execute('SELECT * FROM translation_calls WHERE request_id=?',(bound.request_id,)).fetchone()
                if saved is None:
                    connection.execute('INSERT INTO translation_calls(request_id,job_id,phase,candidate,connection_attempt,status) VALUES (?,?,?,?,?,?)',
                        (bound.request_id,job['id'],request.phase,request.candidate,connection_attempt,'pending'))
            if saved and saved['status']=='completed':
                response=self._decode_response(json.loads(saved['response_json']))
                self._record_usage(job,bound,port,response)
                return response
            if saved:
                prior=await port.request_status(bound.request_id)
                if prior=='completed' and hasattr(port,'recover'):
                    response=await port.recover(bound.request_id)
                elif prior not in ('not_started','not_found','failed'):
                    raise PortUnavailable('PREVIOUS_CALL_STATUS_UNKNOWN')
                else:
                    # Confirmed failed calls consume a separate connection retry;
                    # do not re-execute an already issued request identifier.
                    continue
            else:
                with closing(self.database.connect()) as connection:
                    task=self.router.require_current(connection,route)
                    from app.runtime.state_machine import checkpoint_for
                    checkpoint=checkpoint_for(task)
                    runtime_budget=checkpoint.get('runtime_budget') or checkpoint.get('task_contract',{}).get('budget',{})
                limit=self.max_b_tokens if self.max_b_tokens is not None else runtime_budget.get('total_tokens')
                if limit is not None:
                    summary=UsageLedger(self.database_path).summary(job['task_id'])
                    estimate=len(json.dumps(bound.__dict__,ensure_ascii=False).encode())*2+1024
                    from app.usage.budgets import check_budget
                    gate=check_budget(summary,total_tokens=limit,reserved_a_tokens=runtime_budget.get('reserved_a_tokens',0),role='B',estimated_tokens=estimate)
                    if not gate['allowed']:
                        raise PortUnavailable('TRANSLATION_BUDGET_EXHAUSTED')
                    bound=TranslationRequest(**{**bound.__dict__,'estimated_tokens':estimate,'token_budget_remaining':gate['remaining_tokens']})
                try:
                    response=await port.invoke(bound)
                except (OSError,TimeoutError,PortUnavailable) as error:
                    # Preserve consumed/unknown usage even when no response exists.
                    self._record_usage(job,bound,port,TranslationResponse(complete=False),status='failed')
                    state=await port.request_status(bound.request_id)
                    if state not in ('not_started','not_found','failed'):
                        raise PortUnavailable('PREVIOUS_CALL_STATUS_UNKNOWN') from error
                    with closing(self.database.connect()) as connection:
                        connection.execute("UPDATE translation_calls SET status='failed' WHERE request_id=?",(bound.request_id,))
                    continue
            if not isinstance(response,TranslationResponse):
                self._record_usage(job,bound,port,TranslationResponse(complete=False),status='failed')
                with closing(self.database.connect()) as connection:
                    connection.execute("UPDATE translation_calls SET status='failed' WHERE request_id=?",(bound.request_id,))
                raise PortUnavailable('B_TRANSLATION_RESPONSE_INVALID')
            # A cancelled or invalidated business result can still be billable.
            # Preserve the bound response and receipt before every late fence.
            with closing(self.database.connect()) as connection:
                current=connection.execute('SELECT * FROM task_runs WHERE task_id=? AND attempt_id=?',(job['task_id'],job['attempt_id'])).fetchone()
                flags=json.loads(current['checkpoint_json']) if current else {}
            identity_ok=response.identity==port.identity
            finding_error=None
            try:
                response=replace(response,findings=self._validated_findings(response,bound))
            except PortUnavailable as error:
                finding_error=error
            status='cancelled' if current and current['cancel_requested'] else 'failed' if finding_error or not identity_ok or flags.get('identity_changed') or flags.get('stale') else 'completed'
            self._record_usage(job,bound,port,response,status=status)
            if finding_error:
                with closing(self.database.connect()) as connection,transaction(connection):
                    connection.execute("UPDATE translation_calls SET status='failed',usage_json=? WHERE request_id=?",
                        (json.dumps(response.usage),bound.request_id))
                raise finding_error
            with closing(self.database.connect()) as connection,transaction(connection):
                connection.execute("UPDATE translation_calls SET status=?,response_json=?,usage_json=? WHERE request_id=?",
                    ('completed' if status=='completed' else 'failed',json.dumps(self._response_json(response)),json.dumps(response.usage),bound.request_id))
            if not identity_ok: raise PortUnavailable('B_TRANSLATION_IDENTITY_CHANGED')
            with closing(self.database.connect()) as connection:
                self.router.require_current(connection,route)
            if self.max_b_tokens is not None and UsageLedger(self.database_path).summary(job['task_id'])['known_lower_bound']>self.max_b_tokens:
                raise PortUnavailable('TRANSLATION_BUDGET_EXHAUSTED')
            return response
        raise PortUnavailable('CONNECTION_RETRY_EXHAUSTED')

    def result(self,job_id,*,cache_hit=False):
        with closing(self.database.connect()) as connection:
            job=connection.execute('SELECT * FROM translation_jobs WHERE id=?',(job_id,)).fetchone()
            if job is None: raise ValueError('TRANSLATION_JOB_NOT_FOUND')
            text=self.store.read(job['target_sha256']).decode() if job['status']=='READY' else None
            candidate=connection.execute('SELECT blocks_json FROM translation_candidates WHERE job_id=? ORDER BY candidate DESC LIMIT 1',(job_id,)).fetchone()
            mapping=json.loads(candidate[0]) if candidate else {}
            return TranslationResult(job_id,job['status'],text,job['source_sha256'],job['target_sha256'],job['qa_id'],job['attempt_count'],cache_hit,job['clarification'],tuple({'block_id':key,'target':value} for key,value in mapping.items()))

    async def translate(self,*,task_id,attempt_id,source,source_language,target_language,purpose,source_ref=None,
            context_sha256=None,glossary_version='1',format='markdown',source_version_id=None,source_locator='text',
            budget_id=None,job_id=None,explicit_retry=False):
        route=self.router.lock(task_id,attempt_id)
        if route.route_policy=='native':
            # This API is the forced lane; explicit translation is a distinct task.
            return TranslationResult('', 'NATIVE',source,hashlib.sha256(source.encode()).hexdigest(),None,None,0)
        source_hash=hashlib.sha256(source.encode()).hexdigest()
        context_hash=context_sha256 or hashlib.sha256((task_id+':'+purpose).encode()).hexdigest()
        direction=f'{source_language}->{target_language}'
        translator_role=load_role_prompt('translate','glm',target_language=target_language)
        checker_role=load_role_prompt('check','glm',target_language=target_language)
        role_binding={name:{key:role[key] for key in ('id','version','sha256','assets')}
            for name,role in (('translator',translator_role),('checker',checker_role))}
        role_binding['checker_identity']=self.checker.identity.model_dump(mode='json')
        role_policy_hash=hashlib.sha256(json.dumps(role_binding,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        policy_version=self.policy_version+':roles:'+role_policy_hash
        model_version=self.translator.identity.identity.model_id+':'+self.translator.identity.connection_version
        glossary_snapshot=GlossaryStore(self.database_path).snapshot(task_id,glossary_version)
        key=cache_key(task_id=task_id,source_sha256=source_hash,direction=direction,context_sha256=context_hash,
            glossary_version=glossary_version,glossary_domain=glossary_snapshot.domain,
            glossary_content_sha256=glossary_snapshot.content_sha256,
            policy_version=policy_version,translator_model_version=model_version)
        segments=segment_document(source,format=format,document_version=source_hash,locator=source_locator)
        protected=tuple(protect(s) for s in segments)
        source_blob=self.store.put(source.encode())
        if source_ref and source_ref.startswith('blob:sha256:') and source_ref!=self.store.uri_for(source_blob.sha256):
            raise ValueError('SOURCE_REFERENCE_HASH_MISMATCH')
        with closing(self.database.connect()) as connection,transaction(connection):
            self.router.require_current(connection,route)
            if job_id:
                job=connection.execute('SELECT * FROM translation_jobs WHERE id=? AND task_id=? AND attempt_id=?',(job_id,task_id,attempt_id)).fetchone()
                if job is None or job['cache_key']!=key: raise ValueError('TRANSLATION_JOB_BINDING_MISMATCH')
            else:
                job=None if explicit_retry else connection.execute('SELECT * FROM translation_jobs WHERE task_id=? AND attempt_id=? AND cache_key=? AND source_locator=? ORDER BY created_at DESC LIMIT 1',(task_id,attempt_id,key,source_locator)).fetchone()
            if job is None:
                job_id=uuid4().hex
                contract=TranslationJob(id=job_id,task_id=task_id,turn_id=route.turn_id,source_ref=source_ref or self.store.uri_for(source_hash),source_sha256=source_hash,source_language=source_language,target_language=target_language,glossary_version=glossary_version,policy_version=policy_version,purpose=purpose,status='PENDING',attempt_count=0,budget_id=budget_id or task_id)
                connection.execute('INSERT INTO translation_jobs(id,task_id,attempt_id,turn_id,route_snapshot_id,job_json,source_ref,source_sha256,source_version_id,source_locator,direction,context_sha256,glossary_version,policy_version,translator_model_version,cache_key,segments_json,status) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                    (job_id,task_id,attempt_id,route.turn_id,route.id,contract.model_dump_json(),self.store.uri_for(source_hash),source_hash,source_version_id,source_locator,direction,context_hash,glossary_version,policy_version,model_version,key,json.dumps([s.to_dict() for s in segments]),'PENDING'))
                job=connection.execute('SELECT * FROM translation_jobs WHERE id=?',(job_id,)).fetchone()
            job=dict(job); job_id=job['id']
            if job['status'] in ('READY','FAILED','NEEDS_INPUT','STALE','CANCELLED'):
                terminal=True
            else: terminal=False
            cached=connection.execute('SELECT * FROM translation_cache WHERE cache_key=? AND valid=1',(key,)).fetchone()
        if terminal: return self.result(job_id)
        glossary=glossary_snapshot.entries
        previous={}; findings=()
        if cached:
            blocks=json.loads(cached['blocks_json']); oldqa=TranslationQA.model_validate_json(cached['qa_json'])
            qa,targets,ready=evaluate(job_id,1,segments,protected,blocks,semantic_findings=[f.model_dump() for f in oldqa.semantic_findings],verifier_model=oldqa.verifier_model,semantic_complete=True,format=format,target_language=target_language,reject_english_copies=purpose=='clarification')
            text=''.join(targets)
            if ready and hashlib.sha256(text.encode()).hexdigest()==cached['target_sha256']:
                self._save_candidate(job,1,blocks,qa,targets,ready,{},cache=True)
                return self.result(job_id,cache_hit=True)
        with closing(self.database.connect()) as connection:
            prior=connection.execute('SELECT * FROM translation_candidates WHERE job_id=? ORDER BY candidate DESC LIMIT 1',(job_id,)).fetchone()
        start=job['attempt_count']+1
        if prior:
            previous=json.loads(prior['blocks_json']); findings=tuple(json.loads(prior['qa_json'])['semantic_findings'])
        elif job['attempt_count']:
            start=job['attempt_count']  # recover the persisted in-flight candidate
        for candidate in range(start,4):
            with closing(self.database.connect()) as connection,transaction(connection):
                self.router.require_current(connection,route)
                connection.execute("UPDATE translation_jobs SET status='RUNNING',attempt_count=? WHERE id=?",(candidate,job_id))
            request=TranslationRequest(f'{job_id}:translate:{candidate}',job_id,task_id,attempt_id,candidate,'translate',source_language,target_language,
                tuple(dict(block_id=s.block_id,source=b.text,source_locator=s.source_locator,kind=s.kind) for s,b in zip(segments,protected)),context_hash,glossary,previous,findings,tuple(s.block_id for s in segments if high_impact(s)),
                role_prompt=deepcopy(translator_role))
            try:
                response=await self._call(job,request,self.translator,route)
                # Compare the current candidate in a fresh context, without the
                # translator's prior-candidate QA findings or execution history.
                check_request=TranslationRequest(f'{job_id}:check:{candidate}',job_id,task_id,attempt_id,
                    candidate,'check',source_language,target_language,request.blocks,context_hash,
                    glossary=glossary,previous=response.blocks,high_impact_blocks=request.high_impact_blocks,
                    role_prompt=deepcopy(checker_role))
                check=await self._call(job,check_request,self.checker,route)
                qa,targets,ready=evaluate(job_id,candidate,segments,protected,response.blocks,semantic_findings=(*response.findings,*check.findings),
                    verifier_model=self.checker.identity.identity.model_id,complete=response.complete,semantic_complete=check.complete,format=format,target_language=target_language,reject_english_copies=purpose=='clarification')
            except PortUnavailable as exc:
                with closing(self.database.connect()) as connection:
                    connection.execute("UPDATE translation_jobs SET status='FAILED',clarification=? WHERE id=?",(str(exc),job_id))
                return self.result(job_id)
            self._save_candidate(job,candidate,response.blocks,qa,targets,ready,previous)
            if ready: return self.result(job_id)
            if any(f.code in ('AMBIGUITY','OCR_AMBIGUITY','MISSING_SOURCE') for f in qa.semantic_findings):
                with closing(self.database.connect()) as connection:
                    connection.execute("UPDATE translation_jobs SET status='NEEDS_INPUT',clarification=? WHERE id=?",('请明确存在歧义的要求或补充清晰的原始材料。',job_id))
                return self.result(job_id)
            previous=response.blocks; findings=tuple(f.model_dump() for f in qa.semantic_findings)
        return self.result(job_id)

    def _save_candidate(self,job,candidate,blocks,qa,targets,ready,previous,cache=False):
        target=''.join(targets); ref=self.store.put(target.encode())
        difference={key:{'before':previous.get(key),'after':value} for key,value in blocks.items() if previous.get(key)!=value}
        with closing(self.database.connect()) as connection,transaction(connection):
            from app.contracts.providers import RouteSnapshot
            snapshot=RouteSnapshot.model_validate_json(connection.execute('SELECT snapshot_json FROM route_snapshots WHERE id=?',(job['route_snapshot_id'],)).fetchone()[0])
            self.router.require_current(connection,snapshot)
            connection.execute('INSERT OR REPLACE INTO translation_candidates VALUES (?,?,?,?,?,?)',(job['id'],candidate,json.dumps(blocks),self.store.uri_for(ref.sha256),qa.model_dump_json(),json.dumps(difference)))
            status='READY' if ready else 'FAILED' if candidate==3 else 'REPAIRING'
            connection.execute('UPDATE translation_jobs SET status=?,attempt_count=?,target_ref=?,target_sha256=?,qa_id=? WHERE id=?',
                (status,0 if cache else candidate,self.store.uri_for(ref.sha256) if ready else None,ref.sha256 if ready else None,qa.id,job['id']))
            connection.execute("INSERT OR REPLACE INTO checks(id,task_id,attempt_id,job_id,check_kind,result,severity,check_version,verifier_model,evidence_ref,details_json) VALUES (?,?,?,?,'translation.qa',?,?,?,?,?,?)",
                (qa.id,job['task_id'],job['attempt_id'],job['id'],'pass' if ready else 'fail',qa.severity,qa.check_version,qa.verifier_model,qa.evidence_ref,qa.model_dump_json()))
            if ready and not cache:
                connection.execute('INSERT OR REPLACE INTO translation_cache VALUES (?,?,?,?,?,?,?,?,1)',
                    (job['cache_key'],job['source_sha256'],self.store.uri_for(ref.sha256),ref.sha256,json.dumps(blocks),qa.model_dump_json(),job['glossary_version'],json.dumps({'context_sha256':job['context_sha256'],'model_version':job['translator_model_version']})))
