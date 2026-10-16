"""Private acceptance bootstrap; production never imports this module."""
import os
from pathlib import Path
import sys

root = Path(sys.argv[1])
os.environ['WORKBENCH_API_TOKEN'] = (root / '.service-token').read_text(encoding='utf-8')
sys.argv = ['acceptance-service', '--data-root', str(root / 'service-data'), '--provider-mode', 'fake']
from app.api.launcher import main
main()
