import json
from pathlib import Path
from support.manifest import source_build_id, write_json

OPTIONS_SCHEMA = dict(type='object', additionalProperties=False, properties={
    'fault': dict(enum=['composition_and_internal_replay']),
    'evidence': dict(type='string')})
RESULT_SCHEMA = dict(type='object', additionalProperties=False,
    required=['english_leaks', 'composition_submits', 'focus_lost', 'unmet_checks'], properties={
        'english_leaks': dict(type=['array', 'null']), 'composition_submits': dict(type=['integer', 'null']),
        'focus_lost': dict(type=['boolean', 'null']), 'unmet_checks': dict(type='array', items=dict(type='string')),
        'source': dict(type='string'), 'automatic_checks_passed': dict(type='boolean'),
        'provider_boundary': dict(enum=['fake']), 'real_provider_verified': dict(const=False)})


def automatic_checks_passed(observations):
    return (isinstance(observations, dict) and observations.get('actual_electron') is True
            and observations.get('english_leaks') == []
            and type(observations.get('composition_submits')) is int and observations['composition_submits'] == 0
            and observations.get('focus_lost') is False)


def run(root, options):
    repo = Path(__file__).resolve().parents[3]
    path = repo / options.get('evidence', 'artifacts/qa/D049/gui-observations.json')
    if not path.resolve().is_relative_to(repo):
        raise ValueError('GUI_EVIDENCE_OUTSIDE_REPOSITORY')
    unmet = ['real_windows_ime', 'narrator', 'multiple_monitor_scaling']
    observations = {}
    if path.is_file():
        observations = json.loads(path.read_text(encoding='utf-8'))
        if observations.get('build_id') != source_build_id() or observations.get('actual_electron') is not True:
            unmet.append('current_electron_evidence')
            observations = {}
    else:
        unmet.append('current_electron_evidence')
    passed = automatic_checks_passed(observations)
    if observations and not passed:
        unmet.append('automatic_gui_checks_failed_or_incomplete')
    result = dict(english_leaks=observations.get('english_leaks'),
                  composition_submits=observations.get('composition_submits'),
                  focus_lost=observations.get('focus_lost'), unmet_checks=unmet,
                  source=str(path.relative_to(repo)), automatic_checks_passed=passed,
                  provider_boundary='fake', real_provider_verified=False)
    write_json(root / 'gui-audit.json', result)
    return result
