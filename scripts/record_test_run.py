"""Record a bounded test invocation and its actual exit code as evidence."""
import argparse
import json
import subprocess
import sys
import os
from datetime import datetime,timezone
from pathlib import Path

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',required=True)
    parser.add_argument('--junitxml')
    parser.add_argument('tests',nargs='+')
    args=parser.parse_args()
    output=Path(args.output)
    output.parent.mkdir(parents=True,exist_ok=True)
    command=[sys.executable,'-m','pytest','-q',*args.tests]
    if args.junitxml:
        command.append('--junitxml='+args.junitxml)
    environment=dict(os.environ, PYTHONIOENCODING='utf-8')
    result=subprocess.run(command,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=600,env=environment)
    output.write_text(result.stdout+result.stderr,encoding='utf-8')
    record=dict(time=datetime.now(timezone.utc).isoformat(),command=command,exit_code=result.returncode,git_commit=None,log=str(output))
    output.with_suffix('.json').write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(record))
    raise SystemExit(result.returncode)
