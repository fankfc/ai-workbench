"""Executable checks for the frozen profile conditions, with measured evidence.

These checks prove scoped bytes, structural coverage, rendered files and bounded
numerical results. Claim support, meaning and research design remain A's job.
Code has no implicit execution port. The included local port accepts only
privately registered program/test hashes; it supplies no general OS sandbox.
"""
from collections import Counter
from dataclasses import dataclass
from decimal import Decimal,InvalidOperation
import csv
import io
import json
from pathlib import Path
import re
import subprocess
import sys
from uuid import uuid4

from app.contracts.tasks import safe_relative_scope
from app.documents.model import digest,json_bytes
from app.documents.parse import parse_document
from app.documents.render import DocumentRenderer,_block_text
from app.documents.publish import _verify_rendered_bytes
from app.storage.blobs import read_artifact
from app.storage.revisions import is_current_revision
from app.validation.base import Observation
from .registry import get_profile,validate_profile_contract


CONDITIONS={
    'document':{'source_completeness','requested_formats_and_layout'},
    'paper':{'source_and_citation_trace','reproduction_and_statistics'},
    'code':{'build_and_tests','scope_and_file_integrity'},
}


class CheckFailure(ValueError):
    pass


@dataclass(frozen=True)
class CodeTestRequest:
    task_id:str
    attempt_id:str
    revision_id:str
    program_sha256:str
    program:bytes
    workspace:object
    sources:dict[str,dict]
    test_selector:str


@dataclass(frozen=True)
class CodeTestReceipt:
    task_id:str
    attempt_id:str
    revision_id:str
    program_sha256:str
    test_ref:str
    test_sha256:str
    command:tuple[str,...]
    exit_code:int | None
    stdout:bytes
    stderr:bytes
    tests_run:int | None
    executed:bool
    timed_out:bool
    after_program_sha256:str
    after_test_sha256:str
    qualification_kind:str


class WhitelistedPythonTestsPort:
    """Private fixed-hash qualification followed by actual unittest execution.

    An HTTP/model field cannot install this object or register allowed hashes.
    This narrow service-selected mode is useful for supported fixed programs;
    a general project must inject its independently qualified execution port.
    """
    def __init__(self,*,test_ref,test_sha256,allowed_program_sha256,timeout_seconds=15):
        if not str(safe_relative_scope(test_ref)).startswith('input/'):
            raise ValueError('TEST_SOURCE_SCOPE_INVALID')
        allowed=frozenset(allowed_program_sha256)
        if (not allowed or any(re.fullmatch(r'[a-f0-9]{64}',value) is None for value in (*allowed,test_sha256))
                or type(timeout_seconds) not in (int,float) or not 0<timeout_seconds<=30):
            raise ValueError('FIXED_TEST_QUALIFICATION_REQUIRED')
        self.test_ref,self.test_sha256,self.allowed_program_sha256=test_ref,test_sha256,allowed
        self.timeout_seconds=timeout_seconds;self.executions=0

    def require_qualified(self,request):
        if (type(request) is not CodeTestRequest or request.test_selector!='fixed_python_tests'
                or request.program_sha256 not in self.allowed_program_sha256
                or digest(request.program)!=request.program_sha256):
            raise ValueError('PROGRAM_OR_TEST_SELECTOR_NOT_QUALIFIED')
        source=request.sources.get(self.test_ref)
        if source is None or source['sha256']!=self.test_sha256:
            raise ValueError('TEST_SOURCE_NOT_PINNED_OR_QUALIFIED')
        if digest(request.workspace.read('service',self.test_ref))!=self.test_sha256:
            raise ValueError('TEST_SOURCE_CHANGED')

    def run_tests(self,request):
        self.require_qualified(request)
        program=request.workspace.write('service','artifacts/qt-'+uuid4().hex[:12]+'/c.py',request.program)
        tests=request.workspace.resolve(self.test_ref,'service')
        command=(sys.executable,'-I','-B',str(tests),str(program))
        self.executions+=1
        timed_out=False
        try:
            result=subprocess.run(command,cwd=program.parent,capture_output=True,timeout=self.timeout_seconds,check=False)
            exit_code,stdout,stderr=result.returncode,result.stdout,result.stderr
        except subprocess.TimeoutExpired as error:
            timed_out=True;exit_code=None;stdout=error.stdout or b'';stderr=error.stderr or b''
        count=re.findall(rb'Ran\s+(\d+)\s+tests?\b',stderr)
        return CodeTestReceipt(request.task_id,request.attempt_id,request.revision_id,request.program_sha256,
            self.test_ref,self.test_sha256,command,exit_code,stdout,stderr,int(count[-1]) if count else None,
            True,timed_out,digest(program.read_bytes()),digest(request.workspace.read('service',self.test_ref)),
            'fixed_program_and_test_hashes')


class FrozenProfileChecks:
    def __init__(self,connection,store,candidate,*,execution_port=None,renderer=None):
        self.connection,self.store,self.candidate=connection,store,candidate
        self.execution_port=execution_port;self.renderer=renderer or DocumentRenderer()
        self.contract=candidate.contract;self.catalog=get_profile(self.contract.domain)
        task=connection.execute('SELECT * FROM task_runs WHERE task_id=? AND attempt_id=?',
            (self.contract.task_id,self.contract.attempt_id)).fetchone()
        self.task=task;self.checkpoint=json.loads(task['checkpoint_json']) if task else {}
        self.profile=self.checkpoint.get('task_profile',{})
        self.inputs=self.profile.get('inputs',{})
        self._execution=None;self._sources=None;self._program=None

    def handles(self,criterion):
        return self.contract.domain in CONDITIONS and any(expected['id']==criterion.id for expected in self.catalog['acceptance'])

    def _candidate_bytes(self):
        current_task=self.connection.execute('SELECT * FROM task_runs WHERE task_id=? AND attempt_id=?',
            (self.contract.task_id,self.contract.attempt_id)).fetchone()
        if current_task is None or current_task['cancel_requested']: raise CheckFailure('CURRENT_UNCANCELLED_TASK_REQUIRED')
        artifact=self.connection.execute('SELECT * FROM artifact_revisions WHERE id=? AND task_id=? AND attempt_id=?',
            (self.candidate.revision_id,self.contract.task_id,self.contract.attempt_id)).fetchone()
        if artifact is None or artifact['byte_sha256']!=self.candidate.byte_sha256:
            raise CheckFailure('CANDIDATE_REVISION_BINDING_MISMATCH')
        if not is_current_revision(self.connection,self.contract.task_id,self.contract.attempt_id,self.candidate.revision_id):
            raise CheckFailure('CANDIDATE_REVISION_NOT_CURRENT')
        data=read_artifact(self.connection,self.store,self.candidate.revision_id)
        if (data!=self.candidate.content or Path(self.candidate.artifact_path).resolve()!=self.store.path_for(self.candidate.byte_sha256).resolve()
                or digest(data)!=self.candidate.byte_sha256): raise CheckFailure('CANDIDATE_BYTES_CHANGED')
        return data

    def _load_sources(self):
        sources={}
        for source in self.contract.inputs:
            try:
                data=self.candidate.workspace.read('service',source.ref)
            except (ValueError,OSError,PermissionError) as error:
                raise CheckFailure('SOURCE_BYTES_CHANGED') from error
            if digest(data)!=source.sha256: raise CheckFailure('SOURCE_BYTES_CHANGED')
            sources[source.ref]={'id':source.id,'ref':source.ref,'sha256':source.sha256,'data':data}
        return sources

    def _refs(self,key):
        refs=self.inputs.get(key)
        if not isinstance(refs,list) or not refs or any(not isinstance(ref,str) for ref in refs):
            raise CheckFailure('PROFILE_SOURCE_REFS_NOT_PINNED')
        for ref in refs:
            if ref in ('input/task_profile.md','input/task_profile.json','input/task_profile.yaml'):
                raise CheckFailure('PROFILE_METADATA_IS_NOT_SOURCE')
            if ref not in self._sources: self._sources[ref]=self._material_source(ref)
        return refs

    def _material_source(self,ref):
        """Resolve a raw attachment only through its scoped, pinned full view."""
        materials=self.checkpoint.get('input_materials')
        matches=[item for item in materials if isinstance(item,dict) and item.get('source_ref')==ref] if isinstance(materials,list) else []
        if len(matches)!=1: raise CheckFailure('PROFILE_SOURCE_REFS_NOT_PINNED')
        material=matches[0]
        if (material.get('coverage')!='full' or material.get('parsed') is not True or material.get('text_format')!='markdown'):
            raise CheckFailure('ATTACHMENT_FULL_SOURCE_REQUIRED')
        attachment=self.connection.execute('''SELECT a.* FROM attachments a
            JOIN turn_attachments link ON link.attachment_id=a.id JOIN turns supplied ON supplied.id=link.turn_id
            JOIN turns current ON current.id=? WHERE a.id=? AND a.conversation_id=current.conversation_id
            AND supplied.conversation_id=current.conversation_id AND supplied.rowid<=current.rowid
            AND a.deleted=0 AND a.status='ready' ''',(self.task['turn_id'],material.get('attachment_id'))).fetchone()
        if attachment is None: raise CheckFailure('ATTACHMENT_SOURCE_BINDING_MISMATCH')
        suffix=attachment['name'].rsplit('.',1)[-1].lower()
        if (ref!='input/attachment_'+attachment['id']+'.'+suffix
                or material.get('source_sha256')!=attachment['sha256']):
            raise CheckFailure('ATTACHMENT_SOURCE_BINDING_MISMATCH')
        text_ref=material.get('text_ref');text_source=self._sources.get(text_ref)
        if (text_ref!='input/attachment_'+attachment['id']+'.parsed.md' or text_source is None
                or text_source['sha256']!=material.get('text_sha256')):
            raise CheckFailure('ATTACHMENT_DERIVED_SOURCE_NOT_PINNED')
        try:
            raw=self.candidate.workspace.read('service',ref)
            if raw!=self.store.read(attachment['sha256']) or digest(raw)!=attachment['sha256']:
                raise CheckFailure('ATTACHMENT_SOURCE_BINDING_MISMATCH')
            if suffix in {'txt','md','csv','json'}:
                text=raw.decode('utf-8-sig');scope=[]
            else:
                model=parse_document(raw,suffix,source_version_id=attachment['id'],language='mul')
                if not model.complete: raise CheckFailure('SOURCE_PARSE_INCOMPLETE')
                text='\n\n'.join(block.content for block in model.blocks)
                scope=[dict(block_id=block.block_id,source_locator=block.source_locator,
                    source_sha256=block.source_sha256,kind=block.kind) for block in model.blocks]
        except (UnicodeError,OSError,PermissionError,ValueError) as error:
            if isinstance(error,CheckFailure): raise
            raise CheckFailure('ATTACHMENT_SOURCE_BINDING_MISMATCH') from error
        encoded=text.encode('utf-8')
        if encoded!=text_source['data'] or digest(encoded)!=material['text_sha256']:
            raise CheckFailure('ATTACHMENT_DERIVED_TEXT_MISMATCH')
        if scope!=material.get('block_scope'): raise CheckFailure('ATTACHMENT_BLOCK_COVERAGE_MISMATCH')
        return dict(id=attachment['id'],ref=ref,sha256=attachment['sha256'],data=raw,text_data=encoded,
            derived_text_ref=text_ref,derived_text_sha256=text_source['sha256'],block_scope=scope)

    def _source_models(self,refs):
        result=[]
        for ref in refs:
            source=self._sources[ref];suffix=Path(ref).suffix.lower()
            format={'.docx':'docx','.pdf':'pdf','.md':'markdown','.markdown':'markdown','.txt':'markdown','.json':'markdown'}.get(suffix)
            if format is None: raise CheckFailure('SOURCE_FORMAT_UNSUPPORTED')
            model=parse_document(source['data'],format,source_version_id='source:'+source['id'],language='und')
            if not model.complete: raise CheckFailure('SOURCE_PARSE_INCOMPLETE')
            result.append((source,model))
        return result

    def _model(self):
        model=parse_document(self._program,'markdown',source_version_id=self.candidate.revision_id,language='en')
        if not model.complete: raise CheckFailure('CANDIDATE_PARSE_INCOMPLETE')
        return model

    def _document_source(self):
        models=self._source_models(self._refs('source_refs'));target=self._model()
        numbers=lambda text: Counter(Decimal(number) for number in re.findall(r'(?<![\w.])[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?(?!\w|\.\d)',text))
        expected=Counter()
        for _,model in models:
            expected.update(numbers('\n'.join(_block_text(block) for block in model.blocks)))
        observed=numbers('\n'.join(_block_text(block) for block in target.blocks))
        missing=expected-observed
        details={'sources':[{'ref':source['ref'],'sha256':source['sha256'],'blocks':len(model.blocks),
            'source_locations':[block.source_locator for block in model.blocks],
            **{key:source[key] for key in ('derived_text_ref','derived_text_sha256','block_scope') if key in source}} for source,model in models],
            'source_numbers':{str(k):v for k,v in expected.items()},'candidate_numbers':{str(k):v for k,v in observed.items()},
            'missing_numbers':{str(k):v for k,v in missing.items()},'candidate_blocks':len(target.blocks)}
        return Observation('fail' if missing else 'pass','SOURCE_NUMBERS_MISSING' if missing else 'SOURCE_PARSE_AND_NUMBERS_VERIFIED',
            'source_completeness',details,('source_block_semantic_coverage','factual_fidelity'))

    def _document_formats(self):
        # Parse all declared original sources here too; the format check must
        # not silently bless a candidate detached from corrupt source bytes.
        self._source_models(self._refs('source_refs'))
        formats=self.checkpoint.get('requested_formats')
        declared=self.inputs.get('formats')
        if (not isinstance(formats,list) or not formats or sorted(formats)!=sorted(declared or [])
                or len(formats)!=len(set(formats)) or any(f not in ('markdown','pdf','docx') for f in formats)):
            raise CheckFailure('REQUESTED_FORMATS_MISMATCH')
        model=self._model();rendered=[]
        destination=self.candidate.workspace.resolve('artifacts/pv-'+uuid4().hex[:12],'service',write=True)
        for format in formats:
            try:
                result=self.renderer.render(model,format,evidence_dir=destination)
                if result.qa.get('status')!='pass': raise ValueError('RENDER_QA_NOT_PASS')
                result=_verify_rendered_bytes(result,model,format,destination)
            except (ValueError,OSError,RuntimeError) as error:
                return Observation('blocked','REQUESTED_FORMAT_RENDER_FAILED','requested_formats_and_layout',
                    {'requested_formats':formats,'completed_formats':rendered,'failed_format':format,'error_type':type(error).__name__,
                     'error_code':str(error)},('visual_quality','audience_and_usability'))
            ref=self.candidate.workspace.write('service','artifacts/'+destination.name+'/r.'+{'markdown':'md'}.get(format,format),result.data)
            rendered.append({'format':format,'byte_sha256':digest(result.data),'content_sha256':model.content_sha256,
                'rendered_ref':ref.relative_to(self.candidate.workspace.root).as_posix(),'qa':result.qa})
        return Observation('pass','REQUESTED_FORMATS_ACTUALLY_RENDERED','requested_formats_and_layout',
            {'requested_formats':formats,'rendered_formats':rendered},('visual_quality','audience_and_usability'))

    def _paper_trace(self):
        sources=self._source_models(self._refs('evidence_refs'));text=self._program.decode('utf-8')
        parts=re.split(r'(?im)^\s*#{1,6}\s*(?:references|参考文献)\s*$',text,maxsplit=1)
        pending=('bibliographic_authenticity','source_support_and_uncertainty','method_claim_consistency')
        if len(parts)!=2: return Observation('fail','REFERENCE_SECTION_MISSING','source_and_citation_trace',pending_A_review=pending)
        cited=set(re.findall(r'\[(\d+)\]',parts[0]));definitions={}
        for match in re.finditer(r'(?m)^\s*\[(\d+)\]\s+(.+)$',parts[1]):
            if match[1] in definitions: return Observation('fail','CITATION_STRUCTURE_INVALID','source_and_citation_trace',pending_A_review=pending)
            definitions[match[1]]=match[2]
        if not cited or not cited.issubset(definitions): return Observation('fail','CITATION_STRUCTURE_INVALID','source_and_citation_trace',pending_A_review=pending)
        identifiers={}
        for source,model in sources:
            raw=(source.get('text_data',source['data']).decode('utf-8') if Path(source['ref']).suffix.lower() not in ('.pdf','.docx')
                or 'text_data' in source else '\n\n'.join(block.content for block in model.blocks))
            values=['source:'+source['id']]
            values+=re.findall(r'(?im)^\s*(?:source|source_url|doi|来源)\s*:\s*(\S+)',raw)
            try:
                metadata=json.loads(raw)
                if isinstance(metadata,dict): values+=[str(metadata[key]) for key in ('source_url','doi','url') if isinstance(metadata.get(key),str)]
            except ValueError: pass
            for value in values:
                if value.startswith('source:') or re.match(r'^(https?://|10\.\d{4,9}/)',value):
                    identifiers[value.rstrip('.,;').casefold()]=source
        bindings={}
        for cite in sorted(cited):
            definition=definitions[cite].casefold()
            matched=[(identifier,source) for identifier,source in identifiers.items() if identifier in definition
                and (definition.find(identifier)+len(identifier)==len(definition)
                     or definition[definition.find(identifier)+len(identifier)] in ' \t.,;)]')]
            if not matched: return Observation('fail','CITATION_SOURCE_BINDING_MISSING','source_and_citation_trace',
                {'unbound_citation':cite,'source_sha256':[source['sha256'] for source,_ in sources]},pending)
            identifier,source=matched[0]
            bindings[cite]={'identifier':identifier,'source_ref':source['ref'],'source_sha256':source['sha256']}
        if {value['source_ref'] for value in bindings.values()}!={source['ref'] for source,_ in sources}:
            return Observation('fail','PAPER_EVIDENCE_SOURCE_UNUSED','source_and_citation_trace',{'citation_bindings':bindings},pending)
        return Observation('pass','CITATIONS_BOUND_TO_PINNED_SOURCES','source_and_citation_trace',{'citation_bindings':bindings},pending)

    def _paper_statistics(self):
        refs=self._refs('data_refs');values=[];measured=[]
        try:
            for ref in refs:
                source=self._sources[ref]
                reader=csv.DictReader(io.StringIO(source['data'].decode('utf-8')))
                if not reader.fieldnames or 'value' not in reader.fieldnames: raise CheckFailure('DATA_SCHEMA_UNAVAILABLE')
                count=0
                for row in reader:
                    value=Decimal(row['value'])
                    if not value.is_finite(): raise CheckFailure('DATA_NONFINITE')
                    values.append(value);count+=1
                if not count: raise CheckFailure('REPRODUCTION_DATA_UNAVAILABLE')
                measured.append({'ref':ref,'sha256':source['sha256'],'rows':count})
        except (UnicodeError,InvalidOperation,KeyError,TypeError,csv.Error) as error:
            raise CheckFailure('REPRODUCTION_DATA_INVALID') from error
        n=len(values);total=sum(values,Decimal(0));mean=total/n
        sd=(sum(((value-mean)**2 for value in values),Decimal(0))/(n-1)).sqrt() if n>=2 else None
        statistics={'n':n,'sum':str(total),'mean':str(mean),'min':str(min(values)),'max':str(max(values)),
            'range':str(max(values)-min(values)),'sample_sd':str(sd) if sd is not None else None}
        text=self._program.decode('utf-8');displayed={};checks={}
        for name in statistics:
            tokens=re.findall(r'(?i)\b'+name+r'\s*[:=]\s*([-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)(?!\w|\.\d)',text)
            if not tokens: continue
            if statistics[name] is None: raise CheckFailure('SAMPLE_SD_REQUIRES_TWO_OBSERVATIONS')
            displayed[name]=tokens
            checks[name]=[]
            for token in tokens:
                reported=Decimal(token);actual=Decimal(str(statistics[name]));tolerance=Decimal(0)
                comparison='exact_finite_decimal'
                if name=='n': comparison='exact_integer'
                elif name=='sample_sd' and '.' in token.split('e')[0].split('E')[0]:
                    tolerance=Decimal(1).scaleb(reported.as_tuple().exponent)/2
                    comparison='declared_precision_half_unit'
                passed=abs(reported-actual)<=tolerance and (name!='n' or reported==reported.to_integral_value())
                checks[name].append(dict(reported=token,recomputed=str(actual),comparison=comparison,
                    half_unit_tolerance=str(tolerance),absolute_error=str(abs(reported-actual)),passed=passed))
        if not displayed: raise CheckFailure('RECOMPUTED_STATISTICS_NOT_REPORTED')
        requested=set(re.findall(r'(?i)\b(n|sum|mean|min|max|range|sample_sd)\b',self.inputs.get('research_question','')))
        requested={name.lower() for name in requested}
        if not requested.issubset(displayed): raise CheckFailure('REQUESTED_STATISTICS_NOT_REPORTED')
        match=all(check['passed'] for entries in checks.values() for check in entries)
        return Observation('pass' if match else 'fail','RECOMPUTED_STATISTICS_MATCH' if match else 'RECOMPUTED_STATISTICS_MISMATCH',
            'reproduction_and_statistics',{'inputs':measured,'recomputed_statistics':statistics,'reported_statistics':displayed,
                'reported_checks':checks,'requested_statistics':sorted(requested),
                'method':'value-column pooled n/sum/mean/min/max/range/sample_sd; ddof=1; exact finite Decimal except declared SD half-unit'},
            ('method_claim_consistency','biological_vs_technical_replicates','statistical_design'))

    def _execution_observation(self):
        if self._execution is not None: return self._execution
        port=self.execution_port
        if port is None or not callable(getattr(port,'require_qualified',None)) or not callable(getattr(port,'run_tests',None)):
            self._execution=Observation('blocked','EXECUTION_PORT_UNAVAILABLE','qualified_code_tests');return self._execution
        if self.inputs.get('workspace_ref') not in self._sources: raise CheckFailure('PROFILE_SOURCE_REFS_NOT_PINNED')
        request=CodeTestRequest(self.contract.task_id,self.contract.attempt_id,self.candidate.revision_id,
            self.candidate.byte_sha256,self._program,self.candidate.workspace,self._sources,self.inputs.get('test_command',''))
        try:
            if port.require_qualified(request) is not None: raise ValueError('QUALIFICATION_MUST_VERIFY_CURRENT_REQUEST')
        except (ValueError,OSError,PermissionError,RuntimeError):
            self._execution=Observation('blocked','EXECUTION_PORT_UNQUALIFIED','qualified_code_tests');return self._execution
        try: receipt=port.run_tests(request)
        except (ValueError,OSError,PermissionError,RuntimeError):
            self._execution=Observation('blocked','EXECUTION_PORT_FAILED','qualified_code_tests');return self._execution
        if (type(receipt) is not CodeTestReceipt or (receipt.task_id,receipt.attempt_id,receipt.revision_id,receipt.program_sha256)
                !=(request.task_id,request.attempt_id,request.revision_id,request.program_sha256)
                or receipt.test_ref not in self._sources or receipt.test_sha256!=self._sources[receipt.test_ref]['sha256']
                or receipt.executed is not True or not isinstance(receipt.stdout,bytes) or not isinstance(receipt.stderr,bytes)
                or not receipt.command or not receipt.qualification_kind):
            self._execution=Observation('blocked','EXECUTION_RECEIPT_UNVERIFIED','qualified_code_tests');return self._execution
        details={'execution':{'program_sha256':receipt.program_sha256,'test_ref':receipt.test_ref,'test_sha256':receipt.test_sha256,
            'command':list(receipt.command),'exit_code':receipt.exit_code,'executed':receipt.executed,'timed_out':receipt.timed_out,
            'tests_run':receipt.tests_run,'stdout_sha256':digest(receipt.stdout),'stderr_sha256':digest(receipt.stderr),
            'stdout':receipt.stdout.decode('utf-8',errors='replace'),'stderr':receipt.stderr.decode('utf-8',errors='replace'),
            'qualification_kind':receipt.qualification_kind,'after_program_sha256':receipt.after_program_sha256,
            'after_test_sha256':receipt.after_test_sha256}}
        if receipt.timed_out: status,reason='blocked','EXECUTION_TIMED_OUT'
        elif receipt.after_program_sha256!=receipt.program_sha256 or receipt.after_test_sha256!=receipt.test_sha256:
            status,reason='fail','EXECUTION_SCOPE_INTEGRITY_CHANGED'
        elif type(receipt.tests_run) is not int or receipt.tests_run<1: status,reason='not_verified','ACTUAL_TEST_COUNT_UNAVAILABLE'
        elif type(receipt.exit_code) is not int: status,reason='not_verified','EXECUTION_EXIT_STATUS_UNKNOWN'
        elif receipt.exit_code!=0: status,reason='fail','ACTUAL_BUILD_OR_TESTS_FAILED'
        else: status,reason='pass','QUALIFIED_TESTS_EXECUTED'
        self._execution=Observation(status,reason,'qualified_code_tests',details,('requirements_and_exception_behavior','critical_design'))
        return self._execution

    def evaluate(self,criterion):
        expected=next((value for value in self.catalog['acceptance'] if value['id']==criterion.id),None)
        try:
            if (expected is None or expected['condition']!=criterion.condition or criterion.evidence_type!=expected['evidence_type']
                    or criterion.verifier!='C' or criterion.semantic or criterion.mandatory is not True):
                raise CheckFailure('FROZEN_PROFILE_CONDITION_MISMATCH')
            if not self.profile or self.profile.get('domain')!=self.contract.domain: raise CheckFailure('FROZEN_PROFILE_CONTEXT_REQUIRED')
            validate_profile_contract(self.contract,profile_version=self.profile['version'],inputs=self.inputs)
            self._program=self._candidate_bytes();self._sources=self._load_sources()
            observed={'source_completeness':self._document_source,'requested_formats_and_layout':self._document_formats,
                'source_and_citation_trace':self._paper_trace,'reproduction_and_statistics':self._paper_statistics,
                'build_and_tests':self._execution_observation,'scope_and_file_integrity':self._execution_observation}[criterion.condition]()
            if observed.status=='pass':
                self._candidate_bytes();self._sources=self._load_sources()
                for key in ('source_refs','evidence_refs','data_refs'):
                    if key in self.inputs: self._refs(key)
            return observed
        except CheckFailure as error:
            return Observation('fail',str(error),criterion.condition)
        except (ValueError,KeyError,TypeError,OSError,RuntimeError,PermissionError) as error:
            return Observation('blocked','PROFILE_CHECK_UNAVAILABLE',criterion.condition,{'error_type':type(error).__name__})

    def result(self,criterion):
        observed=self.evaluate(criterion)
        proof={'criterion_id':criterion.id,'revision_id':self.candidate.revision_id,'artifact_sha256':self.candidate.byte_sha256,
            'task_id':self.contract.task_id,'attempt_id':self.contract.attempt_id,'validator_id':'frozen_profile:'+self.contract.domain,
            'validator_version':'1.0','method':criterion.condition,'passed':observed.status=='pass','status':observed.status,
            'reason_code':observed.reason_code,'details':observed.details,'pending_A_review':list(observed.pending_A_review)}
        data=json_bytes(proof);ref='evidence/profile-'+uuid4().hex+'.json'
        try:
            self.candidate.workspace.write('service',ref,data)
            proof.update(evidence_ref=ref,evidence_sha256=digest(data))
        except (ValueError,OSError,PermissionError):
            proof.update(status='blocked',passed=False,reason_code='PROFILE_EVIDENCE_WRITE_FAILED')
        return {'criterion_id':criterion.id,'passed':proof['passed'],'evidence':proof}
