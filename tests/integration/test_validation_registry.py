"""Actual snapshot bytes and mechanical checks; provider prose is not evidence."""
import hashlib
import json
import sys
from pathlib import Path

import pytest

from app.validation.base import ArtifactSnapshot, ValidationContext, CommandResult, NativeMechanicalRunner
from app.validation.registry import Registry


def criterion(evidence_type="artifact", semantic=False):
    return {"id":"ac1","mandatory":True,"verifier":"A" if semantic else "C","evidence_type":evidence_type,"condition":"fixture acceptance","semantic":semantic}


def snapshot(root, name, data, revision="r1"):
    path=root/name
    path.write_bytes(data)
    return ArtifactSnapshot(revision,hashlib.sha256(data).hexdigest(),path)


def context(tmp_path,data=b"print('ok')\n",name="candidate.py",**kwargs):
    return ValidationContext("t","a",snapshot(tmp_path,name,data),[criterion(kwargs.pop("evidence_type","artifact"),kwargs.pop("semantic",False))],tmp_path,**kwargs)


def result(domain,ctx):
    values=Registry().validate(domain,ctx)
    assert len(values)==1
    return values[0]


def test_python_syntax_checks_actual_bytes_and_bound_evidence(tmp_path):
    ctx=context(tmp_path)
    value=result("code",ctx)
    assert value.status=="pass"
    evidence=(tmp_path/value.evidence_ref).read_bytes()
    proof=json.loads(evidence)
    assert proof["criterion_id"]=="ac1" and proof["revision_id"]=="r1"
    assert proof["artifact_sha256"]==ctx.artifact.byte_sha256
    assert hashlib.sha256(evidence).hexdigest()==value.evidence_sha256


def test_broken_python_is_fail(tmp_path):
    assert result("code",context(tmp_path,b"def broken(:\n")).status=="fail"


def test_generated_tests_do_not_replace_execution(tmp_path):
    value=result("code",context(tmp_path,b"def test_ok():\n    assert True\n",evidence_type="execution"))
    assert value.status=="blocked" and value.reason_code=="TOOL_UNAVAILABLE"


def test_unexecuted_command_result_cannot_pass(tmp_path):
    value=result("code",context(tmp_path,evidence_type="execution",commands={"ac1":[sys.executable,"candidate.py"]},runner=lambda *args:CommandResult(0,b"ok",b"",executed=False),execution_authorized=True))
    assert value.status=="not_verified"


@pytest.mark.windows
def test_code_executor_uses_actual_native_process_and_exit(tmp_path):
    from app.runtime.processes import ProcessManager
    manager=ProcessManager(tmp_path/"process-ledger.sqlite3")
    try:
        ctx=context(tmp_path,evidence_type="execution",commands={"ac1":[sys.executable,"candidate.py"]},runner=NativeMechanicalRunner(manager,"t","a"),execution_authorized=True,environment={"test_only":True,"scope":"service-authored fixture"})
        value=result("code",ctx)
        assert value.status=="pass"
        assert json.loads((tmp_path/value.evidence_ref).read_text(encoding="utf-8"))["details"]["stdout"].strip()=="ok"
    finally:
        manager.close()


def test_untrusted_model_code_without_os_sandbox_is_blocked(tmp_path):
    calls=[]
    value=result("code",context(tmp_path,evidence_type="execution",commands={"ac1":[sys.executable,"candidate.py"]},runner=lambda *args:calls.append(args)))
    assert value.reason_code=="OS_SANDBOX_UNVERIFIED" and calls==[]


def test_timed_out_command_is_blocked(tmp_path):
    value=result("code",context(tmp_path,evidence_type="execution",commands={"ac1":[sys.executable,"candidate.py"]},runner=lambda *args:CommandResult(None,b"",b"",timed_out=True),execution_authorized=True))
    assert value.status=="blocked" and value.reason_code=="VALIDATOR_TIMEOUT"


def test_paper_citation_structure_does_not_prove_claim_support(tmp_path):
    value=result("paper",context(tmp_path,b"# Paper\nClaim [1].\n## References\n[1] Author, Title, 2025.\n",name="paper.md"))
    assert value.status=="pass"
    assert value.method=="citation_structure_only"
    assert "claim_support" in value.pending_A_review


def test_undefined_paper_citation_fails(tmp_path):
    value=result("paper",context(tmp_path,b"Claim [99].\n## References\n[1] Title.\n",name="paper.md"))
    assert value.status=="fail"


def test_paper_semantic_claim_remains_pending_A(tmp_path):
    value=result("paper",context(tmp_path,b"Claim [1].\n## References\n[1] Title.\n",name="paper.md",semantic=True))
    assert value.status=="not_verified" and value.reason_code=="PENDING_A_REVIEW"


def test_missing_paper_data_is_not_verified(tmp_path):
    value=result("paper",context(tmp_path,b'{"sum":6}',name="analysis.json",evidence_type="execution"))
    assert value.status=="not_verified" and value.reason_code=="DATA_UNAVAILABLE"


def test_paper_sum_is_recomputed_from_real_csv(tmp_path):
    data=snapshot(tmp_path,"data.csv",b"value\n1\n2\n3\n","data-v1")
    value=result("paper",context(tmp_path,b'{"sum":6}',name="analysis.json",evidence_type="execution",data_inputs={"data":data}))
    assert value.status=="pass"


def test_document_numbers_and_protected_names_match_original(tmp_path):
    source=snapshot(tmp_path,"source.txt","name: 张三\nTotal: 12.5\n".encode(),"source-v1")
    value=result("document",context(tmp_path,"# 报告\nname: 张三\nTotal: 12.5\n".encode(),name="report.md",source=source))
    assert value.status=="pass"


def test_document_changed_number_fails(tmp_path):
    source=snapshot(tmp_path,"source.txt",b"Total: 12.5\n","source-v1")
    value=result("document",context(tmp_path,b"# Report\nTotal: 15.2\n",name="report.md",source=source))
    assert value.status=="fail" and value.reason_code=="SOURCE_NUMBERS_MISMATCH"


def test_document_renderer_missing_is_blocked(tmp_path):
    value=result("document",context(tmp_path,b"# Report\n",name="report.md",evidence_type="render"))
    assert value.status=="blocked" and value.reason_code=="TOOL_UNAVAILABLE"


def test_corrupt_docx_is_fail(tmp_path):
    value=result("document",context(tmp_path,b"PK-not-a-docx",name="report.docx"))
    assert value.status=="fail"


def test_mixed_without_current_dependency_proof_is_blocked(tmp_path):
    value=result("mixed",context(tmp_path,b"# Report\n",name="report.md",evidence_type="dependency"))
    assert value.status=="blocked" and value.reason_code=="DEPENDENCY_GRAPH_UNAVAILABLE"


def test_snapshot_hash_mismatch_cannot_pass(tmp_path):
    ctx=context(tmp_path)
    ctx.artifact.path.write_bytes(b"changed\n")
    value=result("code",ctx)
    assert value.status=="fail" and value.reason_code=="ARTIFACT_HASH_MISMATCH"


def test_artifact_changed_during_command_cannot_keep_pass(tmp_path):
    ctx=context(tmp_path,evidence_type="execution",commands={"ac1":[sys.executable,"candidate.py"]},execution_authorized=True)
    def runner(*args):
        ctx.artifact.path.write_bytes(b"changed during validation")
        return CommandResult(0,b"ok",b"")
    ctx.runner=runner
    value=result("code",ctx)
    assert value.status=="fail" and value.reason_code=="REVISION_CHANGED_DURING_VALIDATION"


def test_boolean_exit_code_is_not_an_execution_pass(tmp_path):
    value=result("code",context(tmp_path,evidence_type="execution",commands={"ac1":[sys.executable,"candidate.py"]},runner=lambda *args:CommandResult(False,b"ok",b""),execution_authorized=True))
    assert value.status=="not_verified" and value.reason_code=="COMMAND_EXIT_STATUS_UNKNOWN"


def test_empty_code_artifact_is_not_valid_deliverable(tmp_path):
    value=result("code",context(tmp_path,b""))
    assert value.status=="fail" and value.reason_code=="ARTIFACT_EMPTY"


def test_nonfinite_paper_data_is_corrupt(tmp_path):
    data=snapshot(tmp_path,"data.csv",b"value\nInfinity\n","data-v1")
    value=result("paper",context(tmp_path,b'{"sum":"Infinity"}',name="analysis.json",evidence_type="execution",data_inputs={"data":data}))
    assert value.status=="fail" and value.reason_code=="DATA_CORRUPT"


def test_pdf_structure_without_renderer_is_blocked(tmp_path):
    source=snapshot(tmp_path,"source.txt",b"Total 3\n","source-v1")
    value=result("document",context(tmp_path,b"%PDF-1.7\n%%EOF",name="report.pdf",source=source))
    assert value.status=="blocked" and value.reason_code=="PDF_RENDERER_REQUIRED"


def test_manual_human_criterion_cannot_get_mechanical_pass(tmp_path):
    ctx=context(tmp_path)
    ctx.criteria=[{**criterion(),"verifier":"human"}]
    value=result("code",ctx)
    assert value.status=="not_verified" and value.reason_code=="HUMAN_REVIEW_REQUIRED"


@pytest.fixture
def revision_storage(tmp_path):
    from test_dependency_invalidation import storage
    fixture=storage.__wrapped__(tmp_path)
    value=next(fixture)
    try:
        yield value
    finally:
        value[1].close()
        fixture.close()


def test_mixed_pass_uses_real_persisted_current_graph(tmp_path,revision_storage):
    from test_dependency_invalidation import chain
    _,connection,store=revision_storage
    chain(connection,store)
    row=connection.execute("SELECT byte_sha256 FROM artifact_revisions WHERE id='report-v1'").fetchone()
    work=tmp_path/"verification"
    work.mkdir()
    ctx=ValidationContext("t","a",ArtifactSnapshot("report-v1",row[0],store.path_for(row[0])),[criterion("dependency")],work,connection=connection,store=store)
    value=result("mixed",ctx)
    assert value.status=="pass"
    proof=json.loads((work/value.evidence_ref).read_text(encoding="utf-8"))
    assert proof["details"]["dependency_fence"]["graph_version"]==7


def test_stale_current_revision_is_rejected_by_validator(tmp_path,revision_storage):
    from test_dependency_invalidation import add,chain
    _,connection,store=revision_storage
    chain(connection,store)
    row=connection.execute("SELECT byte_sha256 FROM artifact_revisions WHERE id='report-v1'").fetchone()
    work=tmp_path/"verification"
    work.mkdir()
    ctx=ValidationContext("t","a",ArtifactSnapshot("report-v1",row[0],store.path_for(row[0])),[criterion("dependency")],work,connection=connection,store=store)
    add(connection,store,"data","data-v2")
    assert result("mixed",ctx).reason_code=="REVISION_NOT_CURRENT"


def test_renderer_exit_zero_without_actual_render_is_not_pass(tmp_path):
    value=result("document",context(tmp_path,b"# Report\n",name="report.md",evidence_type="render",commands={"ac1":["renderer.exe"]},runner=lambda *args:CommandResult(0,b"",b""),execution_authorized=True,rendered_paths={"ac1":tmp_path/"missing.png"}))
    assert value.status=="fail" and value.reason_code=="RENDERED_ARTIFACT_MISSING"


def test_truncated_command_does_not_pass(tmp_path):
    value=result("code",context(tmp_path,evidence_type="execution",commands={"ac1":[sys.executable,"candidate.py"]},runner=lambda *args:CommandResult(0,b"ok",b"",truncated=True),execution_authorized=True))
    assert value.status=="not_verified" and value.reason_code=="VALIDATOR_OUTPUT_TRUNCATED"


def test_actual_source_name_change_is_fail(tmp_path):
    source=snapshot(tmp_path,"source.txt",b"name: Alice\nTotal: 3\n","source-v1")
    value=result("document",context(tmp_path,b"# Report\nname: Bob\nTotal: 3\n",name="report.md",source=source))
    assert value.status=="fail" and value.reason_code=="SOURCE_NAMES_MISMATCH"


@pytest.mark.windows
def test_actual_native_failure_is_not_pass(tmp_path):
    from app.runtime.processes import ProcessManager
    manager=ProcessManager(tmp_path/"process-ledger.sqlite3")
    try:
        value=result("code",context(tmp_path,b"raise SystemExit(7)\n",evidence_type="execution",commands={"ac1":[sys.executable,"candidate.py"]},runner=NativeMechanicalRunner(manager,"t","a"),execution_authorized=True,environment={"test_only":True}))
        assert value.status=="fail" and value.reason_code=="VALIDATOR_COMMAND_FAILED"
    finally:
        manager.close()


def png_fixture():
    import struct,zlib
    def chunk(kind,body):
        return struct.pack(">I",len(body))+kind+body+struct.pack(">I",zlib.crc32(kind+body)&0xffffffff)
    return b"\x89PNG\r\n\x1a\n"+chunk(b"IHDR",struct.pack(">IIBBBBB",1,1,8,6,0,0,0))+chunk(b"IDAT",zlib.compress(b"\0\0\0\0\xff"))+chunk(b"IEND",b"")


def test_render_output_is_checked_as_actual_png_bytes(tmp_path):
    rendered=tmp_path/"page.png"
    calls=[]
    def writes_output(*args):
        calls.append(args)
        rendered.write_bytes(png_fixture())
        return CommandResult(0,b"",b"")
    value=result("document",context(tmp_path,b"# Report\n",name="report.md",evidence_type="render",commands={"ac1":["fixture-renderer.exe"]},runner=writes_output,execution_authorized=True,rendered_paths={"ac1":rendered},environment={"test_only":True,"scope":"renderer output write and decoding fixture"}))
    assert value.status=="pass"
    assert len(calls)==1
    proof=json.loads((tmp_path/value.evidence_ref).read_text(encoding="utf-8"))
    assert proof["details"]["rendered_sha256"]==hashlib.sha256(rendered.read_bytes()).hexdigest()
    assert "visual_quality" in value.pending_A_review


def test_render_crc_corruption_does_not_pass(tmp_path):
    rendered=tmp_path/"page.png"
    pixels=bytearray(png_fixture())
    pixels[-1]^=1
    def writes_corrupt_output(*args):
        rendered.write_bytes(pixels)
        return CommandResult(0,b"",b"")
    value=result("document",context(tmp_path,b"# Report\n",name="report.md",evidence_type="render",commands={"ac1":["fixture-renderer.exe"]},runner=writes_corrupt_output,execution_authorized=True,rendered_paths={"ac1":rendered}))
    assert value.status=="not_verified" and value.reason_code=="RENDER_OUTPUT_OPENABILITY_UNVERIFIED"


def test_preexisting_render_is_preserved_and_runner_does_not_start(tmp_path):
    rendered=tmp_path/"old-page.png"
    rendered.write_bytes(png_fixture())
    calls=[]
    value=result("document",context(tmp_path,b"# New report\n",name="report.md",evidence_type="render",commands={"ac1":["fixture-renderer.exe"]},runner=lambda *args:calls.append(args) or CommandResult(0,b"",b""),execution_authorized=True,rendered_paths={"ac1":rendered}))
    assert value.status=="blocked" and value.reason_code=="RENDER_OUTPUT_ALREADY_EXISTS"
    assert calls==[] and rendered.read_bytes()==png_fixture()


def test_fresh_render_output_outside_scope_blocks_before_runner(tmp_path):
    from uuid import uuid4
    rendered=tmp_path.parent/("outside-"+uuid4().hex+".png")
    calls=[]
    value=result("document",context(tmp_path,b"# Report\n",name="report.md",evidence_type="render",commands={"ac1":["fixture-renderer.exe"]},runner=lambda *args:calls.append(args) or CommandResult(0,b"",b""),execution_authorized=True,rendered_paths={"ac1":rendered}))
    assert value.status=="blocked" and value.reason_code=="RENDERED_ARTIFACT_SCOPE_INVALID"
    assert calls==[] and not rendered.exists()
