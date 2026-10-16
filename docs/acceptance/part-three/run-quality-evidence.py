"""Generate local quality audit evidence through the actual scenario CLI."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
from uuid import uuid4

REPO=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(REPO/'tests'))
sys.path.insert(0,str(REPO/'services/orchestrator'))
from support.manifest import create_manifest,validate_manifest,write_json
cases=[('D042','requirement_coverage','coverage-report.json'),
       ('D043','translation_corpus','translation-corpus-report.json'),
       ('D044','evaluation_protocol','freeze-audit.json'),
       ('D045','usage_reconciliation','usage-report.json'),
       ('D046','optimization_gate','joint-gate-report.json')]
results=[]
for card,case,report in cases:
    destination=REPO/'artifacts/qa'/card
    destination.mkdir(parents=True,exist_ok=True)
    root=destination/('run-'+uuid4().hex[:12])
    run=subprocess.run([sys.executable,str(REPO/'tests/support/scenario_driver.py'),case,'--root',str(root),'--options','{}'],cwd=REPO,capture_output=True,text=True,encoding='utf-8',timeout=120,check=False)
    if run.returncode:
        print(run.stderr,file=sys.stderr)
        raise SystemExit(run.returncode)
    result=json.loads(run.stdout)
    shutil.copyfile(root/report,destination/report)
    if card=='D045':
        shutil.copyfile(root/'usage-ledger.jsonl',destination/'usage-ledger.jsonl')
    manifest=create_manifest(destination,[p for p in destination.rglob('*') if p.is_file() and p.name!='evidence-manifest.json'])
    write_json(destination/'evidence-manifest.json',manifest)
    if not validate_manifest(destination,manifest)['valid']:
        raise RuntimeError('QUALITY_EVIDENCE_HASH_INVALID')
    results.append(dict(card=card,case=case,run_root=root.relative_to(REPO).as_posix(),report=(destination/report).relative_to(REPO).as_posix(),exit_code=run.returncode,result=result))
output=REPO/'docs/acceptance/part-three/quality-evidence-runs.json'
output.write_text(json.dumps(results,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({item['card']:item['exit_code'] for item in results}))
