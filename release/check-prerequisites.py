"""Native format prerequisite proof; missing tools are a hard failure, no skips."""
import json
from pathlib import Path
import platform
import sys
import uuid
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'services/orchestrator'))
from app.documents.parse import parse_document
from app.documents.render import DocumentRenderer

if __name__ == '__main__':
    output = ROOT / 'artifacts/qa/prerequisites'
    output.mkdir(parents=True, exist_ok=True)
    renderer = DocumentRenderer()
    report = {'source_kind':'local_prerequisite_probe', 'platform':platform.platform(),
              'python':platform.python_version(), 'capabilities':renderer.capabilities(), 'blocked_reasons':[]}
    if sys.platform != 'win32' or sys.version_info[:3] != (3,13,0):
        report['blocked_reasons'].append('pinned_Windows_Python_3_13_0')
    if not report['capabilities']['pdf']:
        report['blocked_reasons'].append('CJK_font_simsun_missing')
    if not report['capabilities']['docx_visual']:
        report['blocked_reasons'].append('native_Word_compatible_COM_renderer_missing')
    if not report['blocked_reasons']:
        try:
            model = parse_document('# Format prerequisite\n\n中文输入法与版式能力核验。'.encode('utf-8'), 'markdown', source_version_id='prerequisite-fixture', language='zh-CN')
            directory = output / ('run-' + uuid.uuid4().hex)
            renderer.render(model, 'pdf', evidence_dir=directory / 'pdf')
            renderer.render(model, 'docx', evidence_dir=directory / 'docx')
            report['actual_pdf_and_docx_render'] = True
        except (ValueError, OSError, RuntimeError) as error:
            report['blocked_reasons'].append('native_format_smoke:' + str(error))
    (output / 'format-prerequisites.json').write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False))
    raise SystemExit(2 if report['blocked_reasons'] else 0)
