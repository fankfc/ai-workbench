from contextlib import closing
import pytest
from app.documents.composite import CompositePipeline,ANALYSIS_CODE
from app.runtime.workspace import WorkspaceManager


SALES=b'month,category,amount\n2026-01,A,10\n2026-01,B,20\n2026-02,A,15\n2026-02,B,25\n'


def test_actual_subprocess_and_plot_bind_to_exact_csv_and_code(document_task):
    ctx=document_task; db=ctx['client'].app.state.database.path
    result=CompositePipeline(db,WorkspaceManager(db.parent/'workspaces')).run(ctx['task'],ctx['attempt'],SALES)
    assert result['exit_code']==0 and result['results']=={'rows':4,'monthly_totals':{'2026-01':'30','2026-02':'40'},'increase':'10'}
    with closing(ctx['client'].app.state.database.connect()) as c:
        from app.storage.blobs import read_artifact
        assert read_artifact(c,ctx['client'].app.state.blobs,result['analysis_code'])==ANALYSIS_CODE
        assert read_artifact(c,ctx['client'].app.state.blobs,result['figures']).startswith(b'\x89PNG')


def test_missing_row_unqualified_code_and_failed_chart_stop(document_task):
    ctx=document_task; db=ctx['client'].app.state.database.path
    pipeline=CompositePipeline(db,WorkspaceManager(db.parent/'workspaces'))
    with pytest.raises(ValueError,match='CSV_REQUIRED'): pipeline.run(ctx['task'],ctx['attempt'],SALES.rsplit(b'2026-02,B',1)[0])
    with pytest.raises(ValueError,match='QUALIFIED_EXECUTION'): pipeline.run(ctx['task'],ctx['attempt'],SALES,code=b'print("fake")')
    with pytest.raises(ValueError,match='CHART_GENERATION_FAILED'): pipeline.run(ctx['task'],ctx['attempt'],SALES,fail_chart=True)
    with pytest.raises(ValueError,match='CSV_MONTH_LABELS_UNSUPPORTED'):
        pipeline.run(ctx['task'],ctx['attempt'],SALES.replace(b'2026-02',b'2026-03'))


def test_old_conclusion_cannot_pass_merely_by_putting_new_values_in_appendix(document_task):
    from types import SimpleNamespace
    ctx=document_task; db=ctx['client'].app.state.database.path
    pipeline=CompositePipeline(db,WorkspaceManager(db.parent/'workspaces'))
    run=pipeline.run(ctx['task'],ctx['attempt'],SALES.replace(b',25',b',35'))
    candidate=SimpleNamespace(contract=SimpleNamespace(task_id=ctx['task'],attempt_id=ctx['attempt'],
        acceptance=[SimpleNamespace(id='AC1',semantic=False)]),content=b'January 30. February 40. Increase 10.\nAppendix 50 and 20.',byte_sha256='a'*64)
    observed=pipeline.validator(run)(candidate)
    assert observed[0]['passed'] is False
    candidate.content=b'January 30. February 50. Increase 20.'
    assert pipeline.validator(run)(candidate)[0]['passed'] is True
