"""Read-only synthetic decoder comparison; never invokes a transport."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'services/orchestrator'))
from app.contracts.providers import AgentRequest, ProviderIdentity
from app.providers.gpt import CapturedRun, FIXTURE_ARTIFACTS, GptAdapter, decode_capture
from app.providers.zcode import ZCodeAdapter, decode_capture as decode_zcode

SOURCES = [f'services/orchestrator/app/providers/{name}.py' for name in ('base', 'gpt', 'zcode')]
SOURCES += ['services/orchestrator/app/runtime/workflow.py',
            'services/orchestrator/app/api/application.py',
            'services/orchestrator/app/contracts/providers.py',
            'tests/integration/test_backend_vertical.py', 'tests/support/scenario_driver.py']


def hashes():
    return {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in SOURCES}


def main():
    before = hashes()
    cases = []
    records = {
        'codex': [dict(type='thread.started', thread_id='synthetic-execution'),
                  dict(type='item.completed', item=dict(type='agent_message', text='{"decision":"PASS"}')),
                  dict(type='turn.completed', usage=dict(input_tokens=10, output_tokens=2))],
        'zcode': [dict(type='session.created', sessionId='synthetic-execution', seq=1),
                  dict(type='turn.completed', sessionId='synthetic-execution', seq=2, payload=dict(response='{"decision":"PASS"}')),
                  dict(type='result', sessionId='synthetic-execution', response='{"decision":"PASS"}',
                       projection=dict(status='idle'), usage=dict(input_tokens=10, output_tokens=2))],
    }
    for adapter_id, adapter_class, decoder, family in (
            ('codex', GptAdapter, decode_capture, 'gpt'),
            ('zcode', ZCodeAdapter, decode_zcode, 'glm')):
        request = AgentRequest('synthetic-task', 'synthetic-attempt', 'A' if family == 'gpt' else 'B',
                               ProviderIdentity(adapter_id, family + '-fixture', family, 'synthetic-connection'),
                               'not-read.json', 'not-used-workspace', '1.0')
        capture = CapturedRun('\n'.join(json.dumps(item) for item in records[adapter_id]).encode(),
                              0, FIXTURE_ARTIFACTS,
                              metadata=dict(source='provider_response_metadata', model_id=family + '-fixture',
                                            request_id='synthetic-request', external_execution_id='synthetic-execution'))
        decoded = decoder(request, capture)
        usage = next(event.payload for event in decoded.events if event.kind == 'provider.usage')
        started = next(event.payload for event in decoded.events if event.kind == 'provider.started')
        cases.append(dict(adapter=adapter_id, synthetic_decode_success=decoded.success,
                          identity_status=decoded.identity_status, emitted_kinds=[event.kind for event in decoded.events],
                          candidate_events=sum(event.kind == 'artifact.candidate' for event in decoded.events),
                          review_events=sum(event.kind == 'review.decision' for event in decoded.events),
                          usage_payload=usage, workflow_expected_raw_present='raw' in usage,
                          started_payload=started, actual_request_id_emitted='external_request_id' in started,
                          scope_enforced_attribute=getattr(adapter_class(), 'scope_enforced', None),
                          resume_supported=adapter_class.resume_supported))
    after = hashes()
    evidence = dict(at_utc=datetime.now(timezone.utc).isoformat(),
                    command='services/orchestrator/.venv/Scripts/python.exe docs/acceptance/part-one-closeout/runtime-integration-gap-probe.py',
                    scope='Synthetic capture decoder only; no transport/CLI/API/workflow/model/UI/account action',
                    real_model_starts=0, source_hashes_before=before, source_hashes_after=after,
                    source_unchanged=before == after, cases=cases, exit_code=0)
    destination = Path(__file__).with_name('runtime-integration-gap-evidence.json')
    if destination.exists():
        raise RuntimeError('PRESERVE_REVIEW_EVIDENCE')
    destination.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    if before != after or any(not item['synthetic_decode_success'] for item in cases):
        raise AssertionError('SYNTHETIC_REVIEW_CONDITION_FAILED')
    print(json.dumps(dict(source_unchanged=True, real_model_starts=0, cases=cases)))


if __name__ == '__main__':
    main()
