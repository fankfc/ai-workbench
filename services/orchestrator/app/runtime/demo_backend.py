"""Explicit model response fixtures over the actual planner/workflow/publisher.

The resulting answer demonstrates the application. It does not answer an
arbitrary user task and cannot be registered in a real provider environment.
"""
import asyncio
import hashlib
import json
from pathlib import Path

from app.contracts.providers import ProviderContract, ProviderIdentity
from app.contracts.tasks import CORE_RESPONSIBILITIES
from app.providers.fake import FakeProvider
from app.providers.phase_bridge import PhaseStarted, PhaseCapture, UsageReceipt
from app.usage.budgets import check_budget
from .native_backend import build_native_backend
from .native_executor import NativeTaskExecutor
from .planning import NativeTaskPlanner
from .workspace import WorkspaceManager
from .workflow import Workflow


def fixture_identity(family):
    return ProviderContract.model_validate(dict(schema_version='1.0', provider_id='fake-' + family,
        identity=dict(adapter='fake', model_id='fixture-' + family, family=family, connection_id='fake-' + family),
        identity_status='verified', identity_source='Explicit desktop demonstration fixture; no real model', connection_version='test-only'))


def visible_source(text, *, profiled):
    """Keep user material and human task fields out of the private ref envelope."""
    marker='\n\nTask profile inputs (untrusted):\n'
    if not profiled or marker not in text:
        return text
    material,metadata=text.rsplit(marker,1)
    try:
        fields,_=json.JSONDecoder().raw_decode(metadata.lstrip())
    except (ValueError,TypeError):
        return text
    labels={'audience':'受众','purpose':'用途','research_question':'研究问题',
            'requirements':'要求','test_command':'测试要求'}
    details=[labels[key]+'：'+fields[key] for key in labels if isinstance(fields.get(key),str) and fields[key]]
    return material+ ('\n\n'+'\n'.join(details) if details else '')


class DemoPlannerRuntime:
    classification = 'fixture'
    provider = fixture_identity('gpt')

    async def invoke_text(self, text, **binding):
        await asyncio.sleep(.03)
        context = json.loads(text)
        fixed = context['required_contract_fields']
        contract = dict(**fixed, objective='演示产品流程；外部模型输出是固定测试响应。',
            method='Preserve the full source in a marked demonstration answer.',
            constraints=[dict(id='preserve', text='Preserve source bytes and identify the response as a demonstration.', mandatory=True)],
            deliverables=[dict(id='answer', kind='document', write_scope='b/demo.md', require_a_canonical=False)],
            acceptance=[dict(id='source-preserved', mandatory=True, verifier='C', evidence_type='artifact', condition='Actual source and immutable candidate hashes agree.', semantic=False),
                        dict(id='demo-review', mandatory=True, verifier='A', evidence_type='review', condition='Fixture response is marked as a demo and preserves user requirements.', semantic=True)],
            budget=dict(total_tokens=300000, reserved_a_tokens=60000), b_write_scopes=['b'],
            a_responsibilities=sorted(CORE_RESPONSIBILITIES), guidance_depth='ordinary')
        contract.setdefault('dependencies', [])
        if context.get('task_profile'):
            contract['acceptance'].extend(context['task_profile']['acceptance'])
            if context.get('profile_inputs',{}).get('formats'):
                contract['deliverables'][0]['require_a_canonical']=True
        key = binding['request_id']
        yield PhaseStarted(key, 'demo-response-' + key, 'demo-execution-' + key)
        # Synthetic counts are retained only in the explicit fake account.
        receipts = (UsageReceipt('demo-usage-' + key, 1, dict(input_tokens=10, output_tokens=5), 'reported'),)
        yield PhaseCapture(key, self.provider, json.dumps(contract, ensure_ascii=False), 'demo-response-' + key, 'demo-execution-' + key, receipts)

    async def cancel(self, task_id, attempt_id):
        return None


class DemoResponseProvider(FakeProvider):
    classification = 'fixture'

    def __init__(self, family):
        super().__init__()
        self.provider = fixture_identity(family)

    async def probe(self):
        return ProviderIdentity(**self.provider.identity.model_dump())

    async def run(self, request):
        prompt = json.loads(Path(request.prompt_path).read_text(encoding='utf-8'))
        package = prompt['evidence_package']
        profiled=any(item['id'].startswith(('document.','paper.','code.','mixed.')) for item in prompt['contract']['acceptance'])
        await asyncio.sleep(.06)
        usage = dict(input_tokens=10, output_tokens=5)
        if prompt['phase'] == 'review':
            candidate = package['candidate_content']
            preserved = all(visible_source(item['content'],profiled=profiled) in candidate for item in package['sources'])
            self.reviews.append(dict(decision='PASS' if preserved and '演示' in candidate else 'BLOCKED',
                canonical_author='A' if any(item.get('require_a_canonical') for item in prompt['contract']['deliverables']) else 'B',
                criterion_results={item['id']:preserved and '演示' in candidate for item in prompt['contract']['acceptance'] if item['verifier']=='A'},
                read_unit_ids=prompt['contract']['source_unit_ids'], usage=usage))
        else:
            source = '\n\n'.join(('```python\n'+item['content'].rstrip('\n')+'\n```' if item['ref'].endswith('.py')
                else '```json\n'+item['content']+'\n```' if item['ref'].startswith('input/composite-results-')
                else visible_source(item['content'],profiled=profiled)) for item in package['sources'])
            analysis=''
            if prompt['contract'].get('dependencies'):
                results=next((json.loads(item['content']) for item in package['sources']
                    if item['ref'].startswith('input/composite-results-')),None)
                if results is not None:
                    totals=list(results['monthly_totals'].values())
                    analysis=f"January {totals[0]}. February {totals[1]}. Increase {results['increase']}.\n\n"
            reply=dict(text='# 演示回答\n\n桌面流程已运行。以下是收到的材料；本回答来自固定演示响应。\n\n' + source,
                language='zh-CN', usage=usage)
            if analysis: reply['text']='# 演示分析\n\n'+analysis+reply['text']
            if prompt['phase']=='takeover': self.takeovers.append(reply)
            else: self.executions.append(reply)
        async for event in super().run(request):
            yield event


def validate_demo(candidate):
    content = candidate.content
    profiled=any(item.id.startswith(('document.','paper.','code.','mixed.')) for item in candidate.contract.acceptance)
    preserved = all(visible_source(candidate.workspace.read('A', item.ref).decode('utf-8'),profiled=profiled) in content.decode('utf-8') for item in candidate.contract.inputs)
    passed = hashlib.sha256(content).hexdigest() == candidate.byte_sha256 and preserved and '演示' in content.decode('utf-8')
    return [dict(criterion_id='source-preserved', passed=passed,
        evidence=dict(sha256=candidate.byte_sha256, preserved=preserved, demonstration_only=True))]


def build_demo_backend(app):
    if app.state.settings.provider_mode != 'fake':
        raise ValueError('EXPLICIT_DEMO_ENVIRONMENT_REQUIRED')
    runtime, executor_b, reviewer_a = DemoPlannerRuntime(), DemoResponseProvider('glm'), DemoResponseProvider('gpt')
    manager = WorkspaceManager(app.state.settings.data_root)
    planner = NativeTaskPlanner(app.state.database.path, manager, runtime, allow_fixture=True, estimated_tokens=24)
    def validate(candidate):
        from .native_validation import NativeRegistryValidator
        checks=NativeRegistryValidator(app.state.database.path)(candidate)
        return [value for value in checks if value['criterion_id']!='source-preserved']+validate_demo(candidate)
    workflow = Workflow(app.state.database.path, manager, executor_b, validate, reviewer_a, check_budget,
        estimated_tokens={'B.execution': 24, 'A.takeover': 24, 'A.review': 24}, profile_ids={'A': 'fake-gpt', 'B': 'fake-glm'})
    return build_native_backend(planner, NativeTaskExecutor(workflow),
        provider_registry={'fake-gpt': runtime, 'fake-glm': executor_b}, allow_fixture=True)
