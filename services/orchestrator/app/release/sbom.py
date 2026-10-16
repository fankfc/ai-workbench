"""Deterministic CycloneDX lock inventory, explicitly short of a packaged SBOM."""
import json
import tomllib
from .evidence import sha256


def inventory(root):
    npm = json.loads((root / 'package-lock.json').read_text(encoding='utf-8'))
    uv = tomllib.loads((root / 'services/orchestrator/uv.lock').read_text(encoding='utf-8'))
    components = []
    for path, value in sorted(npm.get('packages', {}).items()):
        if not path or not value.get('version'):
            continue
        name = value.get('name') or path.rsplit('node_modules/', 1)[-1]
        item = dict(type='library', group='npm', name=name, version=value['version'],
                    **{'bom-ref': 'npm:' + path}, properties=[{'name': 'inventory:scope', 'value': 'lockfile'}])
        if value.get('license'):
            item['licenses'] = [{'license': {'name': value['license']}}]
        else:
            item['properties'].append({'name': 'license:status', 'value': 'unverified'})
        if value.get('integrity'):
            item['properties'].append({'name': 'npm:integrity', 'value': value['integrity']})
        components.append(item)
    for value in uv.get('package', []):
        components.append(dict(type='library', group='pypi', name=value['name'], version=value['version'],
                               **{'bom-ref': 'pypi:' + value['name'] + '@' + value['version']},
                               properties=[{'name': 'inventory:scope', 'value': 'lockfile'}, {'name': 'license:status', 'value': 'unverified'}],
                               hashes=[{'alg': 'SHA-256', 'content': entry['hash'].split(':', 1)[1]}
                                       for entry in ([value['sdist']] if value.get('sdist') else []) + value.get('wheels', [])
                                       if entry.get('hash', '').startswith('sha256:')]))
    properties = [{'name': 'lock:' + name, 'value': sha256(root / name)}
                  for name in ('package-lock.json', 'services/orchestrator/uv.lock')]
    properties += [{'name': 'inventory:status', 'value': 'lock_inventory_only'},
                   {'name': 'package:runtime_tools', 'value': 'unverified: Python runtime, OCR, format tools and licenses require staged-package inventory'},
                   {'name': 'package:signing', 'value': 'unverified'},
                   {'name': 'package:electron_builder', 'value': next((item['version'] for item in components if item['group'] == 'npm' and item['name'] == 'electron-builder'), 'missing_from_lock')}]
    return dict(bomFormat='CycloneDX', specVersion='1.6', version=1,
                metadata={'component': {'type': 'application', 'name': 'AI Workbench', 'version': '0.1.0'}, 'properties': properties},
                components=components)

