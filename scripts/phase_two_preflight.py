"""Record actual local readiness, without starting an external model or guessing IDs."""
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'services/orchestrator'))


def readiness():
    from app.api.application import create_app
    from app.config import AppSettings
    with tempfile.TemporaryDirectory(prefix='phase-two-readiness-') as directory:
        app = create_app(AppSettings(Path(directory), 'readiness-only-local-token-00000000', 'real', False))
        with closing(app.state.database.connect()) as connection:
            configured = connection.execute('SELECT id,family,identity_status,enabled FROM provider_profiles').fetchall()
        available = [dict(row) for row in configured if row['enabled'] and row['identity_status'] == 'verified' and row['id'] in app.state.provider_registry]
        return dict(schema_version='1.0', generated_at=datetime.now(timezone.utc).isoformat(),
            provider_mode='real', configured_connections=len(configured), available_profiles=available,
            registered_runtime_count=len(app.state.provider_registry), model_calls=0,
            ready=False, status='BLOCKED',
            blockers=['D004_CLAUDE_RUNTIME_NOT_QUALIFIED', 'D005_GLM_GENERATION_NOT_QUALIFIED',
                      'D020_REAL_VERTICAL_NOT_ACCEPTED', 'GPT_CURRENT_LIFECYCLE_QUALIFICATION_MISSING'],
            real_profile_ids_recorded=False, evidence='docs/acceptance/part-one-progress.md')


def frozen_scenarios():
    domains = {
        'code': ('code.zh.md', ['add.py', 'test_add.py.txt'], ['code', 'test_results'], ['signed_addition', 'scope_integrity', 'A_design_review']),
        'paper': ('paper.zh.md', ['observations.csv'], ['pdf', 'docx'], ['mean=2.5', 'range=1..4', 'no_causal_claim', 'A_evidence_review']),
        'document': ('document.zh.md', ['source.zh.md'], ['markdown', 'docx', 'pdf'], ['complete_source', 'negative_threshold=-0.03', 'uncertainty_preserved', 'A_audience_review']),
        'composite': ('composite.zh.md', ['sales.csv'], ['code', 'csv', 'png', 'pdf'], ['v1=30,40,10', 'v2=30,50,20', 'fresh_dependencies', 'historical_v1_retained']),
    }
    scenarios = []
    for domain, (request, inputs, formats, criteria) in domains.items():
        paths = [ROOT / 'tests/fixtures/vertical' / name for name in [request, *inputs]]
        scenarios.append(dict(domain=domain, request=str(paths[0].relative_to(ROOT)).replace('\\', '/'),
            inputs=[dict(path=str(path.relative_to(ROOT)).replace('\\', '/'), sha256=hashlib.sha256(path.read_bytes()).hexdigest()) for path in paths],
            requested_formats=formats, required_criteria=criteria, provider_mode='real',
            model_families=['claude', 'gpt'], b_family='glm', budget_tokens=300000,
            reserved_a_tokens=60000, budget_seconds=480, status='BLOCKED',
            requires=['actual_gui_submission', 'verified_model_identity', 'A_B_C_A_evidence', 'download_hashes', 'cancel_and_restart', 'domain_human_review']))
    return dict(schema_version='1.0', frozen_at=datetime.now(timezone.utc).isoformat(), scenarios=scenarios,
                evaluated=False, quality_equivalence_claim=False, token_savings_claim=False)


if __name__ == '__main__':
    destination = ROOT / 'docs/acceptance/part-two'
    destination.mkdir(parents=True, exist_ok=True)
    result = readiness()
    (destination / 'real-readiness.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    (ROOT / 'docs/acceptance/vertical-scenarios.json').write_text(json.dumps(frozen_scenarios(), ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False))
