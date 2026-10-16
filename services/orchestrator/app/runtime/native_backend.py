"""Private assembly of supplied runtimes; construction never probes or starts them."""
import asyncio
from contextlib import closing
import inspect
from pathlib import Path

from app.contracts.providers import ProviderContract
from app.providers.phase_bridge import PhaseBridge
from app.providers.native_rpc import RpcCleanup
from app.storage.database import Database
from .native_executor import NativeTaskExecutor
from .planning import NativeTaskPlanner, PreparedPlan
from .publication import PublicationBlocked
from .state_machine import checkpoint_for, require_current_attempt
from .supervisor import NativeBackendBindings, SupervisorError


def build_native_backend(planner, executor, *, provider_registry=None, allow_fixture=False):
    if (type(planner) is not NativeTaskPlanner or type(executor) is not NativeTaskExecutor
            or type(allow_fixture) is not bool):
        raise SupervisorError('PRIVATE_BACKEND_PORTS_REQUIRED')
    workflow = executor.workflow
    if (Path(planner.database_path).resolve() != Path(executor.database_path).resolve()
            or planner.workspaces.data_root != workflow.workspaces.data_root):
        raise SupervisorError('PRIVATE_BACKEND_DATABASE_MISMATCH')
    roles = (workflow.adapter, workflow.reviewer)
    runtimes = (planner.runtime, *(port.runtime if isinstance(port, PhaseBridge) else port for port in roles))
    classification = getattr(planner.runtime, 'classification', None)
    if classification not in {'production', 'fixture'}:
        raise SupervisorError('PRIVATE_BACKEND_BINDING_REQUIRED')
    if classification == 'fixture':
        if not allow_fixture or not planner.allow_fixture or not isinstance(provider_registry, dict):
            raise SupervisorError('EXPLICIT_FIXTURE_BACKEND_REQUIRED')
    elif any(not isinstance(port, PhaseBridge) for port in roles):
        raise SupervisorError('PRIVATE_PHASE_BRIDGE_REQUIRED')
    derived = {}
    providers = []
    for port, runtime in zip((planner.runtime, *roles), runtimes):
        provider = getattr(runtime, 'provider', None)
        try:
            if not isinstance(provider, ProviderContract) or getattr(port, 'provider', provider) != provider:
                raise ValueError('identity binding')
            provider.require_executable()
            if not callable(getattr(runtime, 'cancel', None)):
                raise ValueError('cleanup unavailable')
            if classification == 'production':
                expected = {'gpt': 'codex', 'glm': 'zcode'}[provider.identity.family.value]
                if (getattr(runtime, 'classification', None) != 'production'
                        or provider.identity.adapter != expected
                        or runtime.scope_capability.require_verified(provider) is not None):
                    raise ValueError('qualification')
            elif not (getattr(runtime, 'classification', None) == 'fixture'
                    or getattr(runtime, 'test_only', False) is True):
                raise ValueError('fixture boundary')
            previous = derived.get(provider.provider_id)
            if previous is not None and previous.provider != provider:
                raise ValueError('profile conflict')
            derived.setdefault(provider.provider_id, runtime)
            providers.append(provider)
        except Exception:
            raise SupervisorError('NATIVE_PROVIDER_NOT_QUALIFIED') from None
    if (providers[0].identity.family.value not in {'gpt','claude'}
            or providers[0] != providers[2]
            or workflow.profile_ids.get('A') != providers[2].provider_id
            or workflow.profile_ids.get('B') != providers[1].provider_id):
        raise SupervisorError('PRIVATE_BACKEND_PROFILE_MISMATCH')
    if providers[0].identity.family.value=='claude':
        service=workflow.translation_service
        if service is None or planner.input_pipeline is None or planner.input_pipeline.service is not service:
            raise SupervisorError('PRIVATE_LANGUAGE_PIPELINE_REQUIRED')
    registry = derived if provider_registry is None else provider_registry
    if (not isinstance(registry, dict) or set(registry) != set(derived)
            or any(not any(value is runtime for runtime in runtimes)
                or getattr(value, 'provider', None) != derived[key].provider for key, value in registry.items())):
        raise SupervisorError('PRIVATE_PROVIDER_REGISTRY_REQUIRED')

    # No real configuration has a frozen joint quality/token qualification.
    # Keep actual A identity, translation and complete canonical-body gates;
    # the conservative executor uses that same A for the initial candidate.
    # Fixture workflows retain their existing deterministic B/A test route.
    workflow._production_a_led = classification == 'production'

    async def cancel(task_id, attempt_id):
        async def cleanup(runtime):
            result = runtime.cancel(task_id, attempt_id)
            return await result if inspect.isawaitable(result) else result
        unique = {id(runtime): runtime for runtime in runtimes}
        results = await asyncio.gather(*(cleanup(runtime) for runtime in unique.values()), return_exceptions=True)
        if any(isinstance(result, BaseException) or result is False
                or result is not None and result is not True and (not isinstance(result, RpcCleanup)
                    or result.cleanup_complete is not True
                    or any(getattr(result, field) != 0 for field in ('running', 'open_handles', 'temp_dirs')))
                for result in results):
            raise PublicationBlocked('NATIVE_LOCAL_CLEANUP_UNCONFIRMED')

    async def publish(plan, result):
        if not isinstance(plan, PreparedPlan):
            raise PublicationBlocked('NATIVE_RESULT_BINDING_REQUIRED')
        contract = plan.contract
        with closing(Database(executor.database_path).connect()) as connection:
            row = require_current_attempt(connection, contract.task_id, contract.attempt_id, contract.contract_version)
            handoff = checkpoint_for(row).get('planning_handoff', {})
            if (handoff.get('previous_owner') != plan.owner_token
                    or row['lease_owner'] not in (None, handoff.get('workflow_owner'))):
                raise PublicationBlocked('NATIVE_FOREIGN_OWNER_FENCE')
        return await executor.publish(plan, result)

    return NativeBackendBindings(dict(registry), planner, executor.execute, publish, cancel, classification)
