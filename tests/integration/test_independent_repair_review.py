"""Adversarial probes written independently from the repair implementation."""
from pathlib import Path
from contextlib import closing
import json

import pytest

from test_agent_workflow import execute, prepare
from test_repair_work_orders import approved, finding, responses


@pytest.mark.parametrize("dispatch", ["repair", "takeover"])
def test_actual_failure_proof_is_current_at_every_repair_dispatch(client, monkeypatch, dispatch):
    from app.runtime.workflow import Workflow

    original = Workflow._transition

    def changed_after_saved_order(self, contract, state, payload=None):
        result = original(self, contract, state, payload)
        if state == "REPAIRING" and payload.get("action") == dispatch:
            checkpoint = json.loads(self._row(contract)["checkpoint_json"])
            order = checkpoint["workflow"]["repair_work_order"]
            evidence_root = self.workspaces.create(contract.task_id, contract.attempt_id).area("evidence")
            proof = evidence_root / order["mechanical_observations"][0]["ref"]
            proof.write_bytes(b'{}')
        return result

    monkeypatch.setattr(Workflow, "_transition", changed_after_saved_order)
    reviews = [dict(decision="REPAIR", findings=[finding()]), approved()]
    if dispatch == "takeover":
        reviews.insert(1, dict(decision="REPAIR", findings=[finding("Same unresolved defect")]))
    case = responses(reviews)
    if dispatch == "takeover":
        case["executions"][1]["text"] = "FAIL still invalid syntax"
    result, b, a = execute(prepare(client), override=case)
    assert result.state == "BLOCKED", result.reason_codes
    assert len(b.starts) == (1 if dispatch == "repair" else 2)
    assert len(a.starts) == (1 if dispatch == "repair" else 2)


@pytest.mark.parametrize("field,value", [("task_id", "foreign-task"), ("attempt_id", "foreign-attempt"),
                                        ("contract_version", "stale-version"), ("revision_id", "foreign-revision")])
def test_explicit_foreign_review_identity_cannot_open_repair_dispatch(client, field, value):
    response = dict(decision="REPAIR", findings=[finding()])
    response[field] = value
    result, b, a = execute(prepare(client), override=responses([response]))
    assert result.state == "BLOCKED" and "A_REVIEW_BINDING_MISMATCH" in result.reason_codes
    assert len(b.starts) == len(a.starts) == 1


def test_private_repair_findings_are_excluded_from_public_events(client):
    from app.api.public_events import public_events
    from app.storage.database import Database

    marker = "PRIVATE-REPAIR-DETAIL-SENTINEL"
    defect = finding(marker)
    defect["id"] = marker
    defect["required_change"] = marker
    prepared = prepare(client)
    result, _, _ = execute(prepared, override=responses([
        dict(decision="REPAIR", findings=[defect]), approved()]))
    assert result.state == "OUTPUT_PREPARING"
    with closing(Database(prepared[0]).connect()) as connection:
        conversation = connection.execute("SELECT conversation_id FROM turns").fetchone()[0]
        private = connection.execute("SELECT internal_payload_json FROM outbox_events").fetchall()
        assert marker in json.dumps([row[0] for row in private])
        assert marker not in json.dumps(public_events(connection, client.app.state.blobs, conversation))
