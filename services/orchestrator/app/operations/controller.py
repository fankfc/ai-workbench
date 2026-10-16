"""Persistent manual operations settings over existing product tables and gates.

No task-state duplication: publication uses the existing release fence, retention
uses the existing reference collector, and glossary history stays immutable.
"""
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from uuid import uuid4

from app.release.evidence import safe_path, sha256
from app.storage.blobs import BlobStore
from app.storage.cleanup import preview
from app.storage.database import Database, transaction
from app.translation.glossary import GlossaryStore

DOMAINS = {'code', 'paper', 'document', 'composite'}
RETENTION = {'diagnostic_logs': 14, 'runtime_events': 90, 'usage_summaries': 365}


def _read(connection):
    row = connection.execute('SELECT version,preferences_json FROM desktop_settings WHERE id=1').fetchone()
    preferences = json.loads(row['preferences_json'])
    value = preferences.get('operations', {'schema_version': '1.0', 'incidents': {}, 'diagnostic_pins': {}, 'glossary_changes': []})
    if not isinstance(value, dict) or value.get('schema_version') != '1.0':
        raise ValueError('OPERATIONS_SETTINGS_INVALID')
    return row['version'], preferences, value


def assert_publication_allowed(connection, task):
    """Called inside the product's existing release transaction."""
    _, _, value = _read(connection)
    incidents = [row for row in value['incidents'].values() if row['status'] == 'open']
    if not incidents:
        return
    checkpoint = json.loads(task['checkpoint_json'])
    domain = checkpoint.get('task_contract', {}).get('domain')
    domain = 'composite' if domain == 'mixed' else domain
    for row in incidents:
        if task['task_id'] in row.get('task_ids', []) or domain in row['domains']:
            # Only a trusted service checkpoint carrying the entire verified
            # configuration can use one explicitly requalified scope. A proof
            # for easy never unlocks hard, another profile, model or policy.
            config = checkpoint.get('optimization_configuration')
            key = checkpoint.get('optimization_qualification_key')
            scope = row.get('requalified_scopes', {}).get(key)
            try:
                from app.quality.eligibility import configuration_key
                matched = (isinstance(config, dict) and isinstance(scope, dict) and config == scope['configuration']
                           and config.get('domain') == domain and configuration_key(config) == key)
            except (ValueError, KeyError, TypeError):
                matched = False
            if not matched:
                raise ValueError('INCIDENT_PUBLICATION_FROZEN')
    if domain not in DOMAINS:
        raise ValueError('INCIDENT_DOMAIN_UNKNOWN')


class OperationsController:
    def __init__(self, database_path):
        self.database = Database(database_path)
        self.root = self.database.path.parent.resolve()
        self.store = BlobStore(self.root / 'blobs')

    def view(self):
        with closing(self.database.connect()) as connection:
            return _read(connection)[2]

    def _edit(self, callback):
        with closing(self.database.connect()) as connection, transaction(connection):
            _, preferences, value = _read(connection)
            result = callback(connection, value)
            preferences['operations'] = value
            connection.execute('UPDATE desktop_settings SET version=version+1,preferences_json=? WHERE id=1', (json.dumps(preferences, ensure_ascii=False),))
            return result

    def record_incident(self, *, domains, qualification_keys, reason, evidence_blobs, task_ids=()):
        if (not isinstance(domains, list) or not domains or not set(domains) <= DOMAINS
                or not isinstance(reason, str) or not reason.strip() or len(reason) > 1000
                or not isinstance(qualification_keys, list) or not all(isinstance(key, str) and key for key in qualification_keys)
                or not isinstance(evidence_blobs, list) or not isinstance(task_ids, (list, tuple))
                or not all(isinstance(task, str) and task for task in task_ids)):
            raise ValueError('INCIDENT_SCOPE_REQUIRED')
        for digest in evidence_blobs:
            self.store.verify(digest)
        identity = uuid4().hex
        def apply(connection, value):
            for task in task_ids:
                if connection.execute('SELECT 1 FROM task_runs WHERE task_id=?', (task,)).fetchone() is None:
                    raise ValueError('INCIDENT_TASK_NOT_FOUND')
            value['incidents'][identity] = dict(status='open', domains=sorted(set(domains)), task_ids=list(task_ids),
                qualification_keys=sorted(set(qualification_keys)), reason=reason, evidence_blobs=list(evidence_blobs),
                created_at=datetime.now(timezone.utc).isoformat(), requalified_scopes={}, publication_frozen=True)
            return identity
        return self._edit(apply)

    def route_for(self, domain, qualification_key):
        if domain not in DOMAINS:
            raise ValueError('OPERATIONS_DOMAIN_INVALID')
        for incident in self.view()['incidents'].values():
            if qualification_key in incident['qualification_keys']:
                return 'a_led'
            if incident['status'] == 'open' and domain in incident['domains']:
                scoped = incident.get('requalified_scopes', {}).get(qualification_key)
                if not scoped or scoped['configuration'].get('domain') != domain:
                    return 'a_led'
        # This only permits a caller's independently qualified route; it creates
        # no qualification and does not select a provider.
        return 'qualified_collaboration'

    def requalify(self, incident_id, registration, evidence, configuration):
        from app.quality.eligibility import evaluate_eligibility
        incident = self.view()['incidents'].get(incident_id)
        if not incident or incident['status'] != 'open':
            raise ValueError('REQUALIFICATION_OPEN_INCIDENT_REQUIRED')
        try:
            observed = datetime.fromisoformat(evidence['observed_at'].replace('Z', '+00:00'))
            created = datetime.fromisoformat(incident['created_at'])
            if observed.tzinfo is None or observed <= created or configuration.get('domain') not in incident['domains']:
                raise ValueError()
            result = evaluate_eligibility(registration, evidence, configuration)
            if not result['eligible'] or not result['optimization_goal_met'] or result['qualification_key'] in incident['qualification_keys']:
                raise ValueError()
        except (KeyError, ValueError, TypeError):
            raise ValueError('REQUALIFICATION_FRESH_INDEPENDENT_EVIDENCE_REQUIRED') from None
        def apply(connection, value):
            current = value['incidents'][incident_id]
            if current != incident:
                raise ValueError('REQUALIFICATION_INCIDENT_CHANGED')
            current['requalified_scopes'][result['qualification_key']] = dict(configuration=configuration,
                candidate_sha256=evidence['candidate_sha256'], commit=evidence['commit'], observed_at=evidence['observed_at'])
            # Keep the wildcard freeze for every scope not independently
            # requalified. This routine never closes an entire domain incident.
            return current
        return self._edit(apply)

    def pin_diagnostic(self, relative):
        if not relative.startswith('diagnostics/'):
            raise ValueError('DIAGNOSTIC_SCOPE_REQUIRED')
        path = safe_path(self.root, relative)
        if not path.is_file() or path.stat().st_nlink != 1:
            raise ValueError('DIAGNOSTIC_FILE_UNSAFE')
        return self._edit(lambda connection, value: value['diagnostic_pins'].update({relative: sha256(path)}))

    def set_retention(self, policy):
        if (not isinstance(policy, dict) or set(policy) != set(RETENTION)
                or any(type(days) is not int or not 1 <= days <= 3650 for days in policy.values())):
            raise ValueError('RETENTION_POLICY_INVALID')
        return self._edit(lambda connection, value: value.update(retention_days=dict(policy)))

    def _retention(self, connection, now):
        if now.tzinfo is None:
            raise ValueError('RETENTION_UTC_TIME_REQUIRED')
        version, _, value = _read(connection)
        policy = value.get('retention_days', RETENTION)
        blob_preview = preview(connection, self.store)
        items = []
        if not blob_preview['blocked']:
            for category, days in policy.items():
                directory = safe_path(self.root, 'diagnostics/' + category)
                if not directory.exists():
                    continue
                for path in sorted(directory.glob('*.json')):
                    relative = path.relative_to(self.root).as_posix()
                    path = safe_path(self.root, relative)
                    if relative in value['diagnostic_pins'] or path.stat().st_nlink != 1:
                        continue
                    age = now.timestamp() - path.stat().st_mtime
                    if age > days * 86400:
                        items.append({'path': relative, 'sha256': sha256(path), 'mtime_ns': path.stat().st_mtime_ns})
        body = {'settings_version': version, 'items': items, 'active_tasks_blocked': blob_preview['blocked'],
                'blob_inventory_version': blob_preview['version'], 'retention_days': policy}
        body['snapshot'] = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
        return body

    def retention_preview(self, now=None):
        with closing(self.database.connect()) as connection:
            return self._retention(connection, now or datetime.now(timezone.utc))

    def apply_retention(self, plan, *, confirmed=False, now=None):
        if confirmed is not True:
            raise ValueError('RETENTION_EXPLICIT_CONFIRMATION_REQUIRED')
        with closing(self.database.connect()) as connection, transaction(connection):
            current = self._retention(connection, now or datetime.now(timezone.utc))
            if current != plan or current['active_tasks_blocked']:
                raise ValueError('RETENTION_SNAPSHOT_STALE')
            for row in current['items']:
                safe_path(self.root, row['path']).unlink()
            return {'removed': [row['path'] for row in current['items']], 'user_content_removed': False}

    def change_glossary(self, task_id, version, domain, entries, *, reason, reviewer):
        if not isinstance(reviewer, str) or not reviewer.strip():
            raise ValueError('GLOSSARY_REVIEWER_REQUIRED')
        glossary = GlossaryStore(self.database.path)
        before = self.view()['glossary_changes']
        glossary.put(task_id, version, domain, entries, reason=reason)
        snapshot = glossary.snapshot(task_id, version)
        def apply(connection, value):
            connection.execute('UPDATE translation_cache SET valid=0 WHERE cache_key IN (SELECT cache_key FROM translation_jobs WHERE task_id=?)', (task_id,))
            value['glossary_changes'].append({'task_id': task_id, 'version': version, 'domain': domain, 'content_sha256': snapshot.content_sha256,
                'reason': reason, 'reviewer': reviewer, 'recorded_at': datetime.now(timezone.utc).isoformat()})
            return {'version': version, 'history_preserved': value['glossary_changes'][:-1] == before, 'cache_invalidated': True}
        return self._edit(apply)
