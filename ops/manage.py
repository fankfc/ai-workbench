"""Manual local operations CLI. No scheduler, messaging, or provider invocation."""
import argparse
import json
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'services/orchestrator'))
from app.operations.controller import OperationsController

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--database', required=True, type=Path)
    parser.add_argument('command', choices=['view','retention-policy','retention-preview','retention-apply','incident','glossary-change','requalify'])
    parser.add_argument('--spec', type=Path)
    parser.add_argument('--confirm', action='store_true')
    args = parser.parse_args()
    if not args.database.is_file():
        parser.error('existing initialized product database required')
    controller = OperationsController(args.database)
    spec = json.loads(args.spec.read_text(encoding='utf-8')) if args.spec else {}
    if args.command == 'view': value = controller.view()
    elif args.command == 'retention-policy': value = controller.set_retention(spec)
    elif args.command == 'retention-preview': value = controller.retention_preview()
    elif args.command == 'retention-apply': value = controller.apply_retention(spec, confirmed=args.confirm)
    elif args.command == 'incident': value = {'incident_id':controller.record_incident(**spec)}
    elif args.command == 'glossary-change': value = controller.change_glossary(**spec)
    else: value = controller.requalify(spec['incident_id'],spec['registration'],spec['evidence'],spec['configuration'])
    print(json.dumps(value, ensure_ascii=False, indent=2))
if __name__ == '__main__':
    main()

