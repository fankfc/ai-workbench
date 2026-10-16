import copy
import hashlib
import json
from pathlib import Path

import pytest

from app.contracts.tasks import contract_digest, evaluate_review, validate_contract
from app.runtime.escalation import choose_escalation


def contract_sample(domain="code"):
    return {
        "task_id": "task", "attempt_id": "attempt", "contract_version": "1.0",
        "domain": domain, "model_family": "claude", "route_snapshot_id": "route",
        "objective": "Produce a verifiable result", "method": "Use source evidence",
        "inputs": [{"id": "input", "ref": "inputs/input.txt", "sha256": "a" * 64}],
        "constraints": [{"id": "C1", "text": "Preserve original evidence", "mandatory": True}],
        "deliverables": [{"id": "D1", "kind": "code" if domain == "code" else "document",
                          "write_scope": "b/result", "require_a_canonical": domain != "code"}],
        "acceptance": [{"id": "AC1", "mandatory": True, "verifier": "C",
                        "evidence_type": "execution", "condition": "Result matches input", "semantic": False},
                       {"id": "AC2", "mandatory": True, "verifier": "A",
                        "evidence_type": "review", "condition": "Reasoning is supported", "semantic": True}],
        "dependencies": [], "budget": {"total_tokens": 10000, "reserved_a_tokens": 2000},
        "b_write_scopes": ["b"], "a_responsibilities": ["problem_modeling", "core_reasoning", "method_choice", "evidence_judgment", "final_review"],
        "guidance_depth": "ordinary", "full_read_required": domain == "paper",
        "source_unit_ids": ["body", "appendix"] if domain == "paper" else ["body"],
    }


def decision_sample(contract, root):
    evidence = []
    for criterion in contract["acceptance"]:
        file = root / (criterion["id"] + ".json")
        file.write_text(json.dumps({"criterion_id": criterion["id"], "revision_id": "rev1", "passed": True}), encoding="utf-8")
        evidence.append({"criterion_id": criterion["id"], "revision_id": "rev1", "ref": file.name,
                         "sha256": hashlib.sha256(file.read_bytes()).hexdigest(),
                         "verifier": criterion["verifier"], "passed": True})
    return {"task_id": "task", "attempt_id": "attempt", "contract_version": "1.0",
            "contract_sha256": contract_digest(contract), "reviewer": "A", "decision": "PASS",
            "revision_id": "rev1", "evidence": evidence, "read_unit_ids": contract["source_unit_ids"],
            "source_refs": ["inputs/input.txt"], "sampling_note": None,
            "canonical_author": "A", "a_response_ref": "responses/a-final", "issues": []}


@pytest.mark.parametrize("domain", ["code", "paper", "document", "mixed"])
def test_four_domains_have_explicit_acceptance_and_b_write_scope(domain):
    value = validate_contract(contract_sample(domain))
    assert value.domain == domain
    assert len(value.acceptance) == 2
    assert value.b_write_scopes == ["b"]


@pytest.mark.parametrize("change", ["duplicate_ac", "empty_ac", "semantic_c", "no_core_reasoning", "unsafe_scope", "no_scope", "reserved_exceeds_budget", "fixed_a_calls"])
def test_invalid_contracts_are_rejected(change):
    value = contract_sample()
    if change == "duplicate_ac":
        value["acceptance"].append(copy.deepcopy(value["acceptance"][0]))
    elif change == "empty_ac":
        value["acceptance"] = []
    elif change == "semantic_c":
        value["acceptance"][1]["verifier"] = "C"
    elif change == "no_core_reasoning":
        value["a_responsibilities"].remove("core_reasoning")
    elif change == "unsafe_scope":
        value["b_write_scopes"] = ["../a"]
    elif change == "no_scope":
        value["b_write_scopes"] = ["other"]
    elif change == "reserved_exceeds_budget":
        value["budget"]["reserved_a_tokens"] = 10001
    else:
        value["max_a_calls"] = 2
    with pytest.raises(ValueError):
        validate_contract(value)


def test_contract_digest_detects_budget_and_acceptance_changes():
    value = contract_sample()
    changed = copy.deepcopy(value)
    changed["budget"]["total_tokens"] += 1
    assert contract_digest(value) != contract_digest(changed)
    changed = copy.deepcopy(value)
    changed["acceptance"][0]["mandatory"] = False
    assert contract_digest(value) != contract_digest(changed)


def test_pass_requires_version_bound_actual_evidence(tmp_path):
    contract = contract_sample()
    decision = decision_sample(contract, tmp_path)
    result = evaluate_review(contract, decision, tmp_path)
    assert result.eligible_for_output
    assert result.decision == "PASS"


@pytest.mark.parametrize("fault", ["missing", "missing_file", "bad_hash", "wrong_revision", "wrong_verifier", "failed_check", "outside", "duplicate"])
def test_missing_or_invalid_evidence_never_passes(tmp_path, fault):
    contract = contract_sample()
    decision = decision_sample(contract, tmp_path)
    item = decision["evidence"][0]
    if fault == "missing":
        decision["evidence"].pop(0)
    elif fault == "missing_file":
        (tmp_path / item["ref"]).unlink()
    elif fault == "bad_hash":
        (tmp_path / item["ref"]).write_text("changed")
    elif fault == "wrong_revision":
        item["revision_id"] = "old"
    elif fault == "wrong_verifier":
        item["verifier"] = "B"
    elif fault == "failed_check":
        item["passed"] = False
    elif fault == "outside":
        item["ref"] = "../outside"
    else:
        decision["evidence"].append(copy.deepcopy(item))
    result = evaluate_review(contract, decision, tmp_path)
    assert not result.eligible_for_output
    assert result.decision == "NEED_EVIDENCE"


@pytest.mark.parametrize("field", ["task_id", "attempt_id", "contract_version", "contract_sha256", "reviewer"])
def test_stale_or_executor_self_review_is_rejected(tmp_path, field):
    contract = contract_sample()
    decision = decision_sample(contract, tmp_path)
    decision[field] = "B" if field == "reviewer" else "stale"
    with pytest.raises(ValueError):
        evaluate_review(contract, decision, tmp_path)


def test_b_document_with_a_pass_is_not_a_canonical_original(tmp_path):
    contract = contract_sample("document")
    decision = decision_sample(contract, tmp_path)
    decision["canonical_author"] = "B"
    result = evaluate_review(contract, decision, tmp_path)
    assert not result.eligible_for_output
    assert "A_CANONICAL_REQUIRED" in result.reason_codes


def test_paper_summary_cannot_replace_full_read_coverage(tmp_path):
    contract = contract_sample("paper")
    decision = decision_sample(contract, tmp_path)
    decision["read_unit_ids"] = ["body"]
    decision["sampling_note"] = "summary only"
    result = evaluate_review(contract, decision, tmp_path)
    assert not result.eligible_for_output
    assert "FULL_READ_INCOMPLETE" in result.reason_codes


@pytest.mark.parametrize("decision", ["REPAIR", "NEED_EVIDENCE", "BLOCKED"])
def test_other_review_outcomes_preserve_explicit_non_delivery(tmp_path, decision):
    contract = contract_sample()
    value = decision_sample(contract, tmp_path)
    value["decision"] = decision
    result = evaluate_review(contract, value, tmp_path)
    assert result.decision == decision
    assert not result.eligible_for_output


@pytest.mark.parametrize("fact,expected", [("ambiguity", "ask_user"), ("evidence_gap", "A_review"), ("assumption_failed", "A_review"), ("method_changed", "A_review"), ("capability_missing", "A_takeover"), ("no_progress", "A_takeover")])
def test_escalation_uses_observed_facts(fact, expected):
    facts = {fact: 2 if fact == "no_progress" else True}
    assert choose_escalation(facts).action == expected


def test_unrecognized_self_confidence_is_not_escalation_evidence():
    with pytest.raises(ValueError):
        choose_escalation({"confidence": 0.99})


def test_default_guidance_does_not_limit_a_calls():
    assert choose_escalation({}).action == "continue"
