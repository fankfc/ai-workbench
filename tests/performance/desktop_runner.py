"""Separate long desktop matrix; does not silently run in the quick suite."""
import argparse
import os
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from support.manifest import source_build_id

parser = argparse.ArgumentParser()
parser.add_argument('--cold-starts', type=int, default=30)
parser.add_argument('--lifecycle-cycles', type=int, default=100)
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()
if not 1 <= args.cold_starts <= 30 or not args.cold_starts <= args.lifecycle_cycles <= 100:
    parser.error('invalid bounded matrix')
args.output.parent.mkdir(parents=True, exist_ok=True)
environment = dict(os.environ, WORKBENCH_QA_BUILD_ID=source_build_id(),
    WORKBENCH_QA_COLD_STARTS=str(args.cold_starts), WORKBENCH_QA_LIFECYCLE_CYCLES=str(args.lifecycle_cycles),
    PLAYWRIGHT_JSON_OUTPUT_FILE=str(args.output.absolute()))
result = subprocess.run(['node', 'node_modules/@playwright/test/cli.js', 'test',
    'tests/e2e/local-performance.spec.ts', '--reporter=json'], env=environment, check=False)
raise SystemExit(result.returncode)
