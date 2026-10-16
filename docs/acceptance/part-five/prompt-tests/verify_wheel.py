"""Run with python -I to prove resource loading from a built wheel only."""
import hashlib
import json
from pathlib import Path
import sys
from zipfile import ZipFile

wheel = Path(sys.argv[1]).resolve(strict=True)
sys.path.insert(0, str(wheel))
import app
from app.runtime.role_prompts import load_role_prompt

assert str(wheel) in app.__file__, app.__file__
roles = [load_role_prompt(phase, family)
    for family in ('gpt', 'claude')
    for phase in ('planning', 'execution', 'review', 'takeover')]
roles += [load_role_prompt(phase, 'glm', target_language=target)
    for target in ('en', 'zh-CN') for phase in ('translate', 'check')]
assets = {}
with ZipFile(wheel) as archive:
    for role in roles:
        assert role['sha256'] == hashlib.sha256(role['instruction'].encode()).hexdigest()
        for asset in role['assets']:
            assert asset['sha256'] == hashlib.sha256(archive.read('app/' + asset['path'])).hexdigest()
            assets[asset['path']] = asset['sha256']
assert len(roles) == 12 and len(assets) == 10
print(json.dumps({'wheel': str(wheel), 'wheel_sha256': hashlib.sha256(wheel.read_bytes()).hexdigest(),
    'app_imported_from': app.__file__, 'loaded_role_contexts': len(roles),
    'asset_count': len(assets), 'assets': assets}, indent=2))
