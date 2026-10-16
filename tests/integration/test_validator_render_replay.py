import hashlib
from app.validation.base import ArtifactSnapshot,ValidationContext,CommandResult
from app.validation.registry import Registry
from test_validation_registry import png_fixture

def test_old_png_and_noop_success_does_not_prove_rendering_current_revision(tmp_path):
    source=tmp_path/'report.md'
    source.write_bytes(b'# New report revision\n')
    output=tmp_path/'old-page.png'
    output.write_bytes(png_fixture())
    calls=[]
    def noop(*args):
        calls.append(args)
        return CommandResult(0,b'',b'')
    criterion=dict(id='render',mandatory=True,verifier='C',evidence_type='render',condition='Render current artifact revision',semantic=False)
    context=ValidationContext('task','attempt',ArtifactSnapshot('new-revision',hashlib.sha256(source.read_bytes()).hexdigest(),source),[criterion],tmp_path,runner=noop,commands={'render':['renderer.exe',str(source)]},execution_authorized=True,rendered_paths={'render':output})
    result=Registry().validate('document',context)[0]
    assert result.status!='pass'
    assert output.read_bytes()==png_fixture()
