"""Private repair instructions derived from a current A review and actual C bytes."""
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

from app.contracts.tasks import ReviewDecision, contract_digest, evaluate_review, safe_relative_scope
from app.providers.phase_bridge import read_mechanical_observations
from .workspace import _reject_reparse


def _semantic_observations(contract, decision, candidate, evidence_root):
    observations = []
    criteria = {item.id: item for item in contract.acceptance}
    seen = set()
    for item in decision.evidence:
        if item.verifier == 'C':
            continue
        criterion = criteria.get(item.criterion_id)
        path = Path(evidence_root) / str(safe_relative_scope(item.ref))
        _reject_reparse(path)
        if (criterion is None or item.verifier != criterion.verifier or item.criterion_id in seen
                or item.revision_id != candidate.revision_id or not path.is_file()
                or path.stat().st_nlink != 1 or path.stat().st_size > 1_048_576):
            raise ValueError('REPAIR_REVIEW_EVIDENCE_INVALID')
        raw = path.read_bytes()
        proof = json.loads(raw)
        if (hashlib.sha256(raw).hexdigest() != item.sha256 or not isinstance(proof, dict)
                or any(proof.get(key) != value for key, value in dict(criterion_id=item.criterion_id,
                    revision_id=candidate.revision_id, byte_sha256=candidate.byte_sha256,
                    verifier=item.verifier).items())
                or type(proof.get('passed')) is not bool or proof['passed'] != item.passed):
            raise ValueError('REPAIR_REVIEW_EVIDENCE_INVALID')
        observations.append(dict(ref=item.ref, sha256=item.sha256, content=raw.decode('utf-8')))
        seen.add(item.criterion_id)
    return observations


def repair_work_order(contract, decision, candidate, evidence_root, review_check_id):
    if (decision.decision != 'REPAIR' or decision.revision_id != candidate.revision_id
            or decision.contract_sha256 != contract_digest(contract)
            or hashlib.sha256(candidate.content).hexdigest() != candidate.byte_sha256):
        raise ValueError('REPAIR_HANDOFF_BINDING_MISMATCH')
    mechanical = [item.model_dump(mode='json') for item in decision.evidence if item.verifier == 'C']
    observations = read_mechanical_observations(contract, candidate.revision_id,
        candidate.byte_sha256, mechanical, evidence_root)
    semantic_observations = _semantic_observations(contract, decision, candidate, evidence_root)
    review = decision.model_dump(mode='json')
    review_bytes = json.dumps(review, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()
    return dict(schema_version='1.0', task_id=contract.task_id, attempt_id=contract.attempt_id,
        contract_version=contract.contract_version, contract_sha256=contract_digest(contract),
        revision_id=candidate.revision_id, byte_sha256=candidate.byte_sha256,
        candidate_content=candidate.content.decode('utf-8'), review_check_id=review_check_id,
        review_record=review, review_record_sha256=hashlib.sha256(review_bytes).hexdigest(),
        findings=[item.model_dump() for item in decision.findings], legacy_issues=list(decision.issues),
        details_complete=bool(decision.findings) and not decision.issues,
        review_scope=list(decision.review_scope),
        allowed_write_scopes=list(contract.b_write_scopes),
        mechanical_evidence=mechanical, mechanical_observations=observations,
        semantic_observations=semantic_observations,
        rerun_checks=[item.model_dump() for item in contract.acceptance],
        requires_reproduction=True,
        instruction='Reproduce each reported failure against this exact candidate and actual evidence. '
            'Repair only within the frozen scopes. Rerun the listed checks on the new revision. '
            'Preserve missing legacy finding details as unknown; request evidence rather than invent them. '
            'A new upstream source or contract requires invalidation and renewed review.')


def require_repair_work_order(contract, order, store, evidence_root, revision_id, review_check_id):
    """Recheck saved handoff bytes and trusted scope immediately before dispatch."""
    if (order.get('revision_id') != revision_id or order.get('review_check_id') != review_check_id):
        raise ValueError('REPAIR_HANDOFF_BINDING_MISMATCH')
    decision = ReviewDecision.model_validate(order.get('review_record'))
    evaluate_review(contract, decision, evidence_root)
    candidate = SimpleNamespace(revision_id=revision_id, byte_sha256=order.get('byte_sha256'),
        content=store.read(order.get('byte_sha256')))
    expected = repair_work_order(contract, decision, candidate, evidence_root, review_check_id)
    if order != expected:
        raise ValueError('REPAIR_HANDOFF_BYTES_CHANGED')
    return order


def takeover_prompt_order(contract, order, views, workspace):
    """Claude receives the same verified English proof view used for this review."""
    if contract.model_family != 'claude':
        return order
    if (not isinstance(views, dict) or views.get('revision_id') != order['revision_id']
            or views.get('review_check_id') != order['review_check_id']):
        raise ValueError('REPAIR_ENGLISH_PROOF_VIEW_REQUIRED')
    observations = views.get('mechanical_observations', [])
    expected = {item['ref']: item['sha256'] for item in order['mechanical_observations']}
    if len(observations) != len(expected) or {item['ref']: item['sha256'] for item in observations} != expected:
        raise ValueError('REPAIR_ENGLISH_PROOF_BINDING_MISMATCH')
    for item in observations:
        if (item.get('language') != 'en' or not item.get('translation_job_id') or not item.get('qa_id')
                or workspace.read('A', item['content_ref']).decode('utf-8') != item['content']
                or hashlib.sha256(item['content'].encode()).hexdigest() != item.get('content_sha256')):
            raise ValueError('REPAIR_ENGLISH_PROOF_VIEW_CHANGED')
    return {**order, 'mechanical_observations': observations, 'evidence_language': 'en'}
