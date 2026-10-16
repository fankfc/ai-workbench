"""Route only on verified model identity; snapshots never change in place."""
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
from uuid import uuid4

from app.contracts.providers import ModelFamily, ProviderIdentity, ProviderContract, RouteSnapshot
from app.runtime.state_machine import checkpoint_for, require_current_attempt
from app.storage.database import Database, transaction


def needs_translation(identity: ProviderIdentity | RouteSnapshot) -> bool:
    family = identity.family if isinstance(identity, ProviderIdentity) else identity.model_family
    if family not in (ModelFamily.CLAUDE, ModelFamily.GPT):
        raise ValueError('UNVERIFIED_MODEL_IDENTITY')
    return family == ModelFamily.CLAUDE


def snapshot_from_provider(provider: ProviderContract, *, task_id, turn_id, attempt_id, policy_version='1.0', snapshot_id=None):
    provider.require_executable()
    if provider.identity.family not in (ModelFamily.CLAUDE, ModelFamily.GPT):
        raise ValueError('UNVERIFIED_MODEL_IDENTITY')
    return RouteSnapshot(id=snapshot_id or uuid4().hex, task_id=task_id, turn_id=turn_id, attempt_id=attempt_id,
        provider_id=provider.provider_id, model_id=provider.identity.model_id, model_family=provider.identity.family,
        adapter_id=provider.identity.adapter, identity_status=provider.identity_status, identity_source=provider.identity_source,
        connection_version=provider.connection_version, policy_version=policy_version,
        route_policy='claude_en_bridge' if provider.identity.family == ModelFamily.CLAUDE else 'native',
        locked_at=datetime.now(timezone.utc))


def persist_snapshot(connection, snapshot):
    """Call in the same transaction that creates turns/task_runs."""
    if not connection.in_transaction:
        raise ValueError('ROUTE_TRANSACTION_REQUIRED')
    snapshot = RouteSnapshot.model_validate(snapshot.model_dump())
    data = snapshot.model_dump_json(); digest = hashlib.sha256(data.encode()).hexdigest()
    old = connection.execute('SELECT * FROM route_snapshots WHERE turn_id=? AND attempt_id=?',(snapshot.turn_id,snapshot.attempt_id)).fetchone()
    if old:
        if old['snapshot_json'] != data:
            raise ValueError('ROUTE_SNAPSHOT_CONFLICT')
        return snapshot
    connection.execute('INSERT INTO route_snapshots(id,task_id,turn_id,attempt_id,snapshot_json,snapshot_sha256) VALUES (?,?,?,?,?,?)',
        (snapshot.id,snapshot.task_id,snapshot.turn_id,snapshot.attempt_id,data,digest))
    return snapshot


class LanguageRouter:
    def __init__(self,database_path):
        self.database = Database(database_path)

    def lock(self, task_id, attempt_id):
        """Register the already immutable task snapshot, including legacy fake rows."""
        with closing(self.database.connect()) as connection, transaction(connection):
            task = require_current_attempt(connection,task_id,attempt_id)
            data=json.loads(task['route_snapshot_json']); data.pop('test_only',None)
            snapshot=RouteSnapshot.model_validate(data)
            if snapshot.identity_status != 'verified':
                raise ValueError('UNVERIFIED_MODEL_IDENTITY')
            persist_snapshot(connection,snapshot)
            return snapshot

    def check_identity(self, task_id, attempt_id, provider):
        with closing(self.database.connect()) as connection, transaction(connection):
            task=require_current_attempt(connection,task_id,attempt_id)
            record=connection.execute('SELECT snapshot_json FROM route_snapshots WHERE task_id=? AND attempt_id=?',(task_id,attempt_id)).fetchone()
            if record is None:
                raise ValueError('LOCKED_ROUTE_REQUIRED')
            snapshot=RouteSnapshot.model_validate_json(record[0])
            if connection.execute('SELECT 1 FROM route_invalidations WHERE route_snapshot_id=?',(snapshot.id,)).fetchone():
                return False
            try:
                snapshot.require_executable(provider)
            except ValueError:
                connection.execute('INSERT INTO route_invalidations(route_snapshot_id,reason,observed_json) VALUES (?,?,?)',(snapshot.id,'MODEL_IDENTITY_CHANGED',provider.model_dump_json()))
                checkpoint=checkpoint_for(task); checkpoint.update(publication_blocked=True,identity_changed=True)
                checkpoint.pop('release_registry',None)
                connection.execute("UPDATE task_runs SET state='PAUSED',checkpoint_json=? WHERE task_id=? AND attempt_id=?",(json.dumps(checkpoint),task_id,attempt_id))
                connection.execute("UPDATE translation_jobs SET status='STALE' WHERE task_id=? AND attempt_id=? AND status NOT IN ('CANCELLED','FAILED')",(task_id,attempt_id))
                return False
            return True

    def require_current(self,connection,route):
        task=require_current_attempt(connection,route.task_id,route.attempt_id)
        record=connection.execute('SELECT * FROM route_snapshots WHERE id=?',(route.id,)).fetchone()
        if (record is None or RouteSnapshot.model_validate_json(record['snapshot_json']) != route
                or connection.execute('SELECT 1 FROM route_invalidations WHERE route_snapshot_id=?',(route.id,)).fetchone()
                or task['cancel_requested'] or checkpoint_for(task).get('identity_changed')):
            raise ValueError('ROUTE_INVALIDATED_OR_CANCELLED')
        return task
