"""Four-domain dispatch with immutable bytes and criterion-bound evidence."""
import hashlib
import json
import os
from pathlib import Path
import sys
import sqlite3
import time
import uuid

from app.contracts.tasks import AcceptanceCriterion
from app.providers.gpt import _safe_payload
from app.storage.revisions import is_current_revision, snapshot_fence
from . import code, document, paper
from .base import Observation, ValidationContext, ValidationResult, snapshot_bytes


class Registry:
    VERSION = "1.0"

    def capabilities(self, domain=None):
        values = {"code":{"registered":True,"methods":["python_ast_parse","native_code_execution"],"execution_requires_injected_tool":True},"paper":{"registered":True,"methods":["citation_structure_only","csv_value_sum"],"claim_support":"pending_A_review"},"document":{"registered":True,"methods":["document_structure_and_source_tokens","native_document_renderer"],"renderer_available_by_default":False},"mixed":{"registered":True,"methods":["persisted_dependency_current"],"dependency_proof_required":True}}
        return values.get(domain,{"registered":False,"status":"unavailable"}) if domain else values

    def validate(self, domain: str, context: ValidationContext):
        if domain not in ("code","paper","document","mixed"):
            raise ValueError("VALIDATOR_DOMAIN_UNAVAILABLE")
        criteria = [AcceptanceCriterion.model_validate(value.model_dump() if isinstance(value,AcceptanceCriterion) else value) for value in context.criteria]
        if len({value.id for value in criteria}) != len(criteria):
            raise ValueError("DUPLICATE_VALIDATION_CRITERION")
        data = None
        failure = None
        try:
            data = snapshot_bytes(context,context.artifact)
            if not data.strip():
                raise ValueError("ARTIFACT_EMPTY")
            if context.connection is not None:
                row = context.connection.execute("SELECT byte_sha256 FROM artifact_revisions WHERE id=? AND task_id=? AND attempt_id=?", (context.artifact.revision_id,context.task_id,context.attempt_id)).fetchone()
                if row is None or row[0] != context.artifact.byte_sha256:
                    raise ValueError("ARTIFACT_REVISION_BINDING_MISMATCH")
                if not is_current_revision(context.connection,context.task_id,context.attempt_id,context.artifact.revision_id):
                    raise ValueError("REVISION_NOT_CURRENT")
        except (OSError,ValueError,sqlite3.Error):
            failure = sys.exc_info()[1].args[0] if isinstance(sys.exc_info()[1],ValueError) else "ARTIFACT_READ_FAILED"
        values = []
        for criterion in criteria:
            started = time.monotonic()
            if failure:
                observed = Observation("fail",failure,"snapshot_binding")
            elif criterion.verifier == "human":
                observed = Observation("not_verified","HUMAN_REVIEW_REQUIRED","manual_review_pending")
            elif criterion.semantic or criterion.evidence_type == "review":
                observed = Observation("not_verified","PENDING_A_REVIEW","semantic_review_pending",pending_A_review=(criterion.condition,))
            elif domain == "mixed":
                observed = self._mixed(context,criterion)
            else:
                observed = {"code":code.validate,"paper":paper.validate,"document":document.validate}[domain](context,criterion,data)
            if observed.status=="pass":
                try:
                    snapshot_bytes(context,context.artifact)
                    if context.source is not None:
                        snapshot_bytes(context,context.source)
                    for source in context.data_inputs.values():
                        snapshot_bytes(context,source)
                    if context.connection is not None and not is_current_revision(context.connection,context.task_id,context.attempt_id,context.artifact.revision_id):
                        raise ValueError("REVISION_NOT_CURRENT")
                except (OSError,ValueError,sqlite3.Error):
                    observed = Observation("fail","REVISION_CHANGED_DURING_VALIDATION",observed.method,pending_A_review=observed.pending_A_review)
            duration = (time.monotonic()-started)*1000
            environment = _safe_payload({"python":sys.version.split()[0],"platform":sys.platform,**context.environment})
            proof = _safe_payload({"criterion_id":criterion.id,"revision_id":context.artifact.revision_id,"artifact_sha256":context.artifact.byte_sha256,"task_id":context.task_id,"attempt_id":context.attempt_id,"passed":observed.status=="pass","status":observed.status,"reason_code":observed.reason_code,"validator_id":domain,"validator_version":self.VERSION,"method":observed.method,"environment":environment,"duration_ms":duration,"details":observed.details,"pending_A_review":observed.pending_A_review})
            reference = digest = None
            try:
                evidence = Path(context.workspace)/"evidence"
                if evidence.is_symlink() or not evidence.resolve().is_relative_to(Path(context.workspace).resolve()):
                    raise OSError("EVIDENCE_SCOPE_INVALID")
                evidence.mkdir(parents=True,exist_ok=True)
                name = f"validator-{domain}-{uuid.uuid4().hex}.json"
                payload = (json.dumps(proof,ensure_ascii=False,sort_keys=True,allow_nan=False)+"\n").encode("utf-8")
                with (evidence/name).open("xb") as handle:
                    handle.write(payload)
                    handle.flush()
                    os.fsync(handle.fileno())
                reference = "evidence/"+name
                digest = hashlib.sha256(payload).hexdigest()
            except (OSError,ValueError):
                observed = Observation("blocked","VALIDATION_EVIDENCE_UNAVAILABLE",observed.method,pending_A_review=observed.pending_A_review)
            values.append(ValidationResult(criterion.id,context.artifact.revision_id,context.artifact.byte_sha256,domain,self.VERSION,observed.status,observed.reason_code,reference,digest,observed.method,environment,duration,observed.pending_A_review))
        return values

    @staticmethod
    def _mixed(context,criterion):
        if criterion.evidence_type != "dependency":
            return Observation("not_verified","CHECK_METHOD_UNAVAILABLE","mixed_unavailable")
        if context.connection is None:
            return Observation("blocked","DEPENDENCY_GRAPH_UNAVAILABLE","persisted_dependency_current")
        try:
            fence = snapshot_fence(context.connection,context.task_id,context.attempt_id,[context.artifact.revision_id])
        except ValueError:
            return Observation("fail","REVISION_NOT_CURRENT","persisted_dependency_current")
        return Observation("pass","DEPENDENCIES_CURRENT","persisted_dependency_current",{"dependency_fence":fence},("overall_design",))
