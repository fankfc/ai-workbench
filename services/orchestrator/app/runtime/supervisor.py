"""Private durable dispatcher. No default provider or automatic qualification."""
import asyncio
from contextlib import closing, suppress
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from types import MappingProxyType
from uuid import uuid4

from app.contracts.providers import ProviderContract, RouteSnapshot
from app.storage.database import Database, transaction
from .outbox import enqueue_event
from .planning import validate_prepared_plan
from .state_machine import checkpoint_for, require_current_attempt, validate_release_gate


class SupervisorError(ValueError):
    pass


@dataclass(frozen=True)
class NativeBackendBindings:
    provider_registry: object
    planner: object
    execute: object
    publish: object
    cancel: object
    classification: str = 'production'

    def __post_init__(self):
        if not isinstance(self.provider_registry, dict):
            raise SupervisorError('PRIVATE_PROVIDER_REGISTRY_REQUIRED')
        object.__setattr__(self, 'provider_registry', MappingProxyType(dict(self.provider_registry)))


class TaskSupervisor:
    def __init__(self, database_path, bindings, *, provider_mode='real', poll_seconds=.05):
        if (type(bindings) is not NativeBackendBindings or provider_mode not in {'real', 'fake'}
                or bindings.classification not in {'production', 'fixture'}
                or (bindings.classification == 'fixture') != (provider_mode == 'fake')
                or type(poll_seconds) not in (int, float) or not .01 <= poll_seconds <= 5):
            raise SupervisorError('PRIVATE_BACKEND_BINDING_REQUIRED')
        if (not callable(getattr(bindings.planner, 'plan', None)) or
                not all(callable(value) for value in (bindings.execute, bindings.publish, bindings.cancel))):
            raise SupervisorError('PRIVATE_BACKEND_PORTS_REQUIRED')
        self.database_path, self.bindings = Path(database_path).resolve(), bindings
        self.database = Database(self.database_path)
        self.workspaces = bindings.planner.workspaces
        if Path(bindings.planner.database_path).resolve() != self.database_path:
            raise SupervisorError('PRIVATE_BACKEND_DATABASE_MISMATCH')
        self._registry = dict(bindings.provider_registry)
        self.provider_registry = MappingProxyType(self._registry)
        self.provider_mode, self.poll_seconds = provider_mode, poll_seconds
        self._closing = False
        self._active = None
        self._active_task = None
        self._cleanup_tasks = {}
        self._operation = asyncio.Lock()
        self.diagnostics = []
        for key, port in self.provider_registry.items():
            self._qualified(key, port)

    def _qualified(self, key, port):
        try:
            provider = port.provider
            if (not isinstance(provider, ProviderContract) or provider.provider_id != key
                    or provider.identity.family.value not in {'gpt', 'glm','claude'}):
                raise ValueError('provider')
            provider.require_executable()
            if self.bindings.classification == 'production':
                expected = {'gpt': 'codex', 'glm': 'zcode'}[provider.identity.family.value]
                if provider.identity.adapter != expected or port.scope_capability.require_verified(provider) is not None:
                    raise ValueError('capability')
        except Exception:
            raise SupervisorError('NATIVE_PROVIDER_NOT_QUALIFIED') from None
        return provider

    def register_profiles(self):
        """Only an injected, qualified runtime can install its private profile."""
        with closing(self.database.connect()) as connection, transaction(connection):
            for key, port in self.provider_registry.items():
                provider = self._qualified(key, port)
                identity = provider.identity
                connection.execute("""INSERT INTO provider_profiles(id,adapter,model_id,family,connection_id,
                    identity_status,identity_source,connection_version,provider_json) VALUES(?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(id) DO UPDATE SET adapter=excluded.adapter,model_id=excluded.model_id,
                    family=excluded.family,connection_id=excluded.connection_id,
                    identity_status=excluded.identity_status,identity_source=excluded.identity_source,
                    connection_version=excluded.connection_version,provider_json=excluded.provider_json""",
                    (key, identity.adapter, identity.model_id, identity.family.value, identity.connection_id,
                     provider.identity_status.value, provider.identity_source, provider.connection_version,
                     provider.model_dump_json()))

    def claim(self):
        if self._closing:
            return None
        with closing(self.database.connect()) as connection, transaction(connection):
            rows = connection.execute("""SELECT r.* FROM task_runs r WHERE r.state='RECEIVED'
                AND r.cancel_requested=0 AND r.lease_owner IS NULL
                AND r.attempt_id=(SELECT attempt_id FROM task_runs n WHERE n.task_id=r.task_id
                    ORDER BY n.attempt_number DESC,n.created_at DESC,n.attempt_id DESC LIMIT 1)
                ORDER BY r.created_at,r.task_id LIMIT 100""").fetchall()
            for row in rows:
                port = self.provider_registry.get(row['provider_profile_id'])
                if port is None:
                    continue
                checkpoint = checkpoint_for(row)
                active = checkpoint.get('active_external_request', {})
                if (row['external_request_id'] or row['external_execution_id']
                        or active.get('accepted') is True or checkpoint.get('a_planning') or checkpoint.get('supervisor')):
                    continue
                try:
                    provider = self._qualified(row['provider_profile_id'], port)
                except SupervisorError:
                    self._registry.pop(row['provider_profile_id'], None)
                    connection.execute('UPDATE provider_profiles SET enabled=0 WHERE id=?', (row['provider_profile_id'],))
                    connection.execute("UPDATE task_runs SET state='BLOCKED' WHERE task_id=? AND attempt_id=?",
                        (row['task_id'], row['attempt_id']))
                    enqueue_event(connection, row['task_id'], row['attempt_id'], 'request.failed',
                        dict(error_code='PROVIDER_UNAVAILABLE'),
                        deduplication_key='supervisor-unqualified:' + row['task_id'] + ':' + row['attempt_id'])
                    continue
                if self.bindings.classification == 'production':
                    try:
                        RouteSnapshot.model_validate_json(row['route_snapshot_json']).require_executable(provider)
                    except ValueError:
                        continue
                elif json.loads(row['route_snapshot_json']).get('test_only') is not True:
                    continue
                owner = 'supervisor:' + uuid4().hex
                checkpoint['supervisor'] = dict(owner_token=owner, stage='claimed',
                    classification=self.bindings.classification)
                expires = (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat()
                connection.execute("""UPDATE task_runs SET state='INPUT_PREPARING',lease_owner=?,
                    lease_expires_at=?,checkpoint_json=? WHERE task_id=? AND attempt_id=?""",
                    (owner, expires, json.dumps(checkpoint), row['task_id'], row['attempt_id']))
                enqueue_event(connection, row['task_id'], row['attempt_id'], 'task.state_changed',
                    dict(expected_state='RECEIVED', new_state='INPUT_PREPARING', contract_version=row['contract_version']),
                    deduplication_key='supervisor-claim:' + row['task_id'] + ':' + row['attempt_id'])
                return dict(task_id=row['task_id'], attempt_id=row['attempt_id'], owner_token=owner)
        return None

    def _current(self, claim):
        with closing(self.database.connect()) as connection:
            return dict(require_current_attempt(connection, claim['task_id'], claim['attempt_id']))

    def _audit_failure(self, claim, reason):
        with closing(self.database.connect()) as connection, transaction(connection):
            row = connection.execute('SELECT * FROM task_runs WHERE task_id=? AND attempt_id=?',
                (claim['task_id'], claim['attempt_id'])).fetchone()
            if row is None:
                return
            try:
                require_current_attempt(connection, claim['task_id'], claim['attempt_id'])
            except ValueError:
                self.diagnostics.append('NATIVE_STALE_ATTEMPT_FENCE')
                return
            checkpoint = checkpoint_for(row)
            marker = checkpoint.get('supervisor', {})
            if marker.get('owner_token') != claim['owner_token']:
                return
            handoff = checkpoint.get('planning_handoff', {})
            owned_handoff = (handoff.get('previous_owner') == claim['owner_token']
                and row['lease_owner'] in (None, handoff.get('workflow_owner')))
            if row['lease_owner'] not in (None, claim['owner_token']) and not owned_handoff:
                self.diagnostics.append('NATIVE_FOREIGN_OWNER_FENCE')
                return
            preserve_ready = False
            if row['state'] == 'READY' and not row['cancel_requested'] and owned_handoff:
                try:
                    validate_release_gate(connection, row, checkpoint)
                    release = checkpoint.get('public_release', {})
                    workflow = checkpoint.get('workflow', {})
                    registry = checkpoint['release_registry']
                    preserve_ready = (release.get('revision_id') == checkpoint.get('current_revision_id')
                        and release.get('source_revision_id',release.get('revision_id')) == workflow.get('current_revision_id')
                        and release.get('review_check_id') == workflow.get('review_check_id')
                        and bool(release.get('review_check_id'))
                        and release.get('approval_id') == registry.get('approval_id')
                        and isinstance(release.get('dependency_fence'), dict)
                        and isinstance(release.get('review_snapshot'), dict))
                except (ValueError, TypeError, KeyError, AttributeError):
                    pass
            marker.update(stage='publication_pending' if preserve_ready else 'stopped', reason_code=reason)
            if not preserve_ready and row['state'] not in {'CANCELLED', 'FAILED', 'PUBLISHED'}:
                enqueue_event(connection, claim['task_id'], claim['attempt_id'], 'request.failed',
                    dict(error_code='PROVIDER_UNAVAILABLE'), deduplication_key='supervisor-error:' + claim['owner_token'])
            if not preserve_ready and row['state'] not in {'CANCELLED', 'FAILED', 'PUBLISHED', 'BLOCKED', 'PAUSED'}:
                connection.execute("UPDATE task_runs SET state='BLOCKED' WHERE task_id=? AND attempt_id=?",
                    (claim['task_id'], claim['attempt_id']))
                enqueue_event(connection, claim['task_id'], claim['attempt_id'], 'task.state_changed',
                    dict(expected_state=row['state'], new_state='BLOCKED', contract_version=row['contract_version']),
                    deduplication_key='supervisor-stop:' + claim['owner_token'])
            connection.execute('UPDATE task_runs SET checkpoint_json=? WHERE task_id=? AND attempt_id=?',
                (json.dumps(checkpoint), claim['task_id'], claim['attempt_id']))
            connection.execute('UPDATE task_runs SET lease_owner=NULL,lease_expires_at=NULL WHERE task_id=? AND attempt_id=? AND lease_owner=?',
                (claim['task_id'], claim['attempt_id'], claim['owner_token']))

    async def _cancel(self, claim):
        key = claim['task_id'], claim['attempt_id']
        if key not in self._cleanup_tasks:
            self._cleanup_tasks[key] = asyncio.create_task(self._cleanup(claim))
        # A watcher and shutdown may await the same attempt. Cancelling one
        # waiter must not abort the owned cleanup or mark its attempt complete.
        await asyncio.shield(self._cleanup_tasks[key])

    async def _cleanup(self, claim):
        key = claim['task_id'], claim['attempt_id']
        try:
            await asyncio.wait_for(self.bindings.cancel(*key), 5)
        except Exception:
            self.diagnostics.append('NATIVE_LOCAL_CLEANUP_UNCONFIRMED')
            self._audit_failure(claim, 'NATIVE_LOCAL_CLEANUP_UNCONFIRMED')

    async def _watch(self, claim, execution, local_stop):
        while not self._closing:
            await asyncio.sleep(self.poll_seconds)
            try:
                row = self._current(claim)
                stopped = row['cancel_requested'] or row['state'] in {'CANCELLED', 'FAILED'}
            except ValueError:
                stopped = True
            if stopped:
                await self._cancel(claim)
                # Cleanup does not guarantee a provider iterator or local port
                # releases its await. End only this owned local operation;
                # persisted remote cancellation remains unconfirmed.
                local_stop.set()
                execution.cancel()
                return

    async def _execute_claim(self, claim):
        plan = await self.bindings.planner.plan(claim['task_id'], claim['attempt_id'], claim['owner_token'])
        from .planning import PlanningNeedsInput, require_planning_clarification
        if isinstance(plan, PlanningNeedsInput):
            # Only an actual completed A request and its trusted
            # clarification publication can end planning without B.
            if (plan.task_id, plan.attempt_id) != (claim['task_id'], claim['attempt_id']):
                raise SupervisorError('NATIVE_CLARIFICATION_SCOPE_CHANGED')
            with closing(self.database.connect()) as connection, transaction(connection):
                require_planning_clarification(self.database_path, plan, connection=connection)
                current=require_current_attempt(connection,plan.task_id,plan.attempt_id)
                if current['lease_owner']!=claim['owner_token']:
                    raise SupervisorError('NATIVE_CLARIFICATION_OWNER_CHANGED')
                connection.execute('UPDATE task_runs SET lease_owner=NULL,lease_expires_at=NULL WHERE task_id=? AND attempt_id=? AND lease_owner=?',
                                   (plan.task_id,plan.attempt_id,claim['owner_token']))
            return plan
        validate_prepared_plan(self.database_path, self.workspaces, plan)
        result = await self.bindings.execute(plan)
        row = self._current(claim)
        if row['cancel_requested'] or row['state'] in {'CANCELLED', 'FAILED'}:
            raise SupervisorError('NATIVE_CANCELLED_FENCE')
        if result.state == 'OUTPUT_PREPARING':
            return await self.bindings.publish(plan, result)
        return result

    async def run_once(self):
        if self._operation.locked() or self._closing:
            return None
        async with self._operation:
            claim = self.claim()
            if claim is None:
                return None
            self._active = claim
            self._active_task = asyncio.current_task()
            local_stop = asyncio.Event()
            execution = asyncio.create_task(self._execute_claim(claim))
            watcher = asyncio.create_task(self._watch(claim, execution, local_stop))
            try:
                return await execution
            except asyncio.CancelledError:
                await self._cancel(claim)
                self._audit_failure(claim, 'NATIVE_LOCAL_WAIT_CANCELLED' if local_stop.is_set() else 'NATIVE_SUPERVISOR_SHUTDOWN')
                if local_stop.is_set() and not self._closing:
                    return None
                raise
            except Exception:
                self._audit_failure(claim, 'NATIVE_DISPATCH_BLOCKED')
                return None
            finally:
                watcher.cancel()
                with suppress(asyncio.CancelledError):
                    await watcher
                self._active = None
                self._active_task = None

    async def run(self):
        while not self._closing:
            await self.run_once()
            await asyncio.sleep(self.poll_seconds)

    async def shutdown(self):
        self._closing = True
        if self._active is not None:
            await self._cancel(self._active)
        if self._cleanup_tasks:
            await asyncio.gather(*(asyncio.shield(task) for task in self._cleanup_tasks.values()))
        if self._active_task is not None and self._active_task is not asyncio.current_task():
            self._active_task.cancel()
