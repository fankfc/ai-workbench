"""Escalate from observed blockers, never self-reported confidence."""
from typing import Literal
from pydantic import StrictBool
from app.contracts.providers import ContractModel, NonNegativeInt

class EscalationFacts(ContractModel):
    ambiguity: StrictBool = False
    evidence_gap: StrictBool = False
    assumption_failed: StrictBool = False
    method_changed: StrictBool = False
    capability_missing: StrictBool = False
    no_progress: NonNegativeInt = 0

class EscalationPlan(ContractModel):
    action: Literal["continue", "ask_user", "A_review", "A_takeover"]
    guidance_depth: Literal["ordinary", "checkpoint", "a_takeover"]
    reason: str

def choose_escalation(facts: dict, current_depth: str = "ordinary") -> EscalationPlan:
    facts = EscalationFacts.model_validate(facts)
    if current_depth not in ("ordinary", "checkpoint", "a_takeover"):
        raise ValueError("INVALID_GUIDANCE_DEPTH")
    if facts.ambiguity:
        return EscalationPlan(action="ask_user", guidance_depth=current_depth, reason="material ambiguity")
    if facts.capability_missing or facts.no_progress >= 2:
        return EscalationPlan(action="A_takeover", guidance_depth="a_takeover", reason="capability or repeated unchanged defect")
    if facts.evidence_gap or facts.assumption_failed or facts.method_changed:
        return EscalationPlan(action="A_review", guidance_depth="a_takeover" if current_depth == "a_takeover" else "checkpoint", reason="evidence or method requires A judgment")
    return EscalationPlan(action="continue", guidance_depth=current_depth, reason="no observed escalation fact")
