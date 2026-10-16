"""Versioned service role instructions, independent of untrusted task content."""
import hashlib
from importlib.resources import files


ROLE_PROMPT_VERSION = '1.0'
_ROLES = {
    'planning': ('A.planning', 'a_planner.v1.md'),
    'execution': ('B.execution', 'b_executor.v1.md'),
    'review': ('A.review', 'a_reviewer.v1.md'),
    'takeover': ('A.takeover', 'a_takeover.v1.md'),
    'translate': ('B.translation', 'b_translator.v1.md'),
    'check': ('B.translation_check', 'b_checker.v1.md'),
}


def load_role_prompt(phase, model_family, *, target_language=None):
    """Return fresh instructions and hashes; this metadata grants no capability."""
    if phase not in _ROLES or model_family not in {'gpt', 'claude', 'glm'}:
        raise ValueError('ROLE_PROMPT_CONTEXT_INVALID')
    if phase in {'translate', 'check'}:
        if model_family != 'glm' or not isinstance(target_language, str) or not target_language.strip():
            raise ValueError('ROLE_PROMPT_TRANSLATION_CONTEXT_REQUIRED')
    elif model_family == 'glm':
        raise ValueError('ROLE_PROMPT_TASK_FAMILY_REQUIRED')
    role_id, asset = _ROLES[phase]
    paths = ['prompts/roles/runtime_boundaries.v1.md', 'prompts/roles/' + asset]
    if phase == 'check':
        paths.append('translation/prompts/semantic_checker.txt')
    elif phase == 'translate' and target_language in {'en', 'zh-CN'}:
        paths.append('translation/prompts/' + ('input_translator.txt' if target_language == 'en' else 'output_translator.txt'))
    parts, assets = [], []
    for path in paths:
        raw = files('app').joinpath(*path.split('/')).read_bytes()
        parts.append(raw.decode('utf-8').strip())
        assets.append({'path': path, 'sha256': hashlib.sha256(raw).hexdigest()})
    language_policy = 'target_language' if phase in {'translate', 'check'} else 'english' if model_family == 'claude' else 'native'
    if language_policy == 'english':
        parts.append('Use English for all natural language in this request and the complete canonical final body.')
    elif language_policy == 'native':
        parts.append('Preserve the original user language. Follow the GPT native route without mandatory translation or bilingual duplication.')
    else:
        parts.append('Use the request target_language for translated blocks. Keep comparison findings separate from translated content.')
    instruction = '\n\n'.join(parts)
    result = {'id': role_id, 'version': ROLE_PROMPT_VERSION, 'phase': phase,
        'instruction': instruction, 'sha256': hashlib.sha256(instruction.encode()).hexdigest(),
        'language_policy': language_policy, 'assets': assets}
    if phase == 'planning':
        result['contract_semantics'] = {
            'key_decisions': ['method', 'a_responsibilities'],
            'worker_autonomy': ['b_write_scopes', 'constraints'],
            'escalation_triggers': ['runner_fixed_escalation_triggers', 'guidance_depth'],
            'acceptance_criteria': ['acceptance'],
        }
    return result
