"""Versioned non-secret preferences and server-owned connection observations."""
from contextlib import closing
from datetime import datetime, timezone
import json
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import Field
from app.contracts.providers import ContractModel
from app.storage.database import transaction

router = APIRouter()
DEFAULTS = dict(theme='system', font_size=16, send_shortcut='enter', close_behavior='quit')


class PreferencesPatch(ContractModel):
    theme: Literal['system', 'light', 'dark'] | None = None
    font_size: int | None = Field(default=None, ge=14, le=22, strict=True)
    send_shortcut: Literal['enter', 'ctrl-enter'] | None = None
    close_behavior: Literal['quit', 'minimize'] | None = None


class SettingsPatch(ContractModel):
    expected_version: int = Field(ge=1, strict=True)
    preferences: PreferencesPatch


def connection_views(request, connection):
    result = []
    mode = request.app.state.settings.provider_mode
    for row in connection.execute('SELECT * FROM provider_profiles ORDER BY family,id'):
        available = bool(row['enabled']) and row['identity_status']=='verified' and row['id'] in request.app.state.provider_registry
        # Configuration and executable runtime qualification are separate facts.
        result.append(dict(id=row['id'], role='B' if row['family'] == 'glm' else 'A',
            family=row['family'], model_id=row['model_id'], identity_status=row['identity_status'],
            enabled=bool(row['enabled']), available=available, provider_mode=mode,
            connection_version=row['connection_version'], capabilities={},
            reason=None if available else '连接尚未完成运行能力验证。'))
    for family in ('claude', 'gpt', 'glm'):
        if not any(item['family'] == family for item in result):
            result.append(dict(id='unconfigured-' + family, role='B' if family == 'glm' else 'A',
                family=family, model_id=None, identity_status='unknown', enabled=False,
                available=False, provider_mode=mode, connection_version=None, capabilities={},
                reason='尚未配置并核验连接。'))
    return result


def settings_view(request, connection):
    row = connection.execute('SELECT version,preferences_json FROM desktop_settings WHERE id=1').fetchone()
    stored = json.loads(row['preferences_json'])
    # The renderer preference form submits this complete public object. Private
    # operations state remains in SQLite and must not enter that IPC contract.
    public = {key: stored.get(key, default) for key, default in DEFAULTS.items()}
    return dict(version=row['version'], preferences=public,
                connections=connection_views(request, connection))


@router.get('/v1/settings')
def get_settings(request: Request):
    with closing(request.app.state.database.connect()) as connection:
        return settings_view(request, connection)


@router.patch('/v1/settings')
def update_settings(body: SettingsPatch, request: Request):
    with closing(request.app.state.database.connect()) as connection, transaction(connection):
        row = connection.execute('SELECT * FROM desktop_settings WHERE id=1').fetchone()
        if body.expected_version != row['version']:
            raise HTTPException(409, '设置已改变，请刷新后重试。')
        preferences = json.loads(row['preferences_json'])
        changes = body.preferences.model_dump(exclude_unset=True)
        if any(value is None for value in changes.values()):
            raise HTTPException(422, '偏好不能为空。')
        preferences.update(changes)
        connection.execute('UPDATE desktop_settings SET version=version+1,preferences_json=? WHERE id=1', (json.dumps(preferences),))
        return settings_view(request, connection)


@router.post('/v1/settings/connections/{profile}/probe')
def probe_connection(profile: str, request: Request):
    with closing(request.app.state.database.connect()) as connection:
        view = next((item for item in connection_views(request, connection) if item['id'] == profile), None)
        if view is None:
            raise HTTPException(404, '连接不存在。')
    # No hidden model request: qualification is supplied by an injected trusted runtime.
    return {**view, 'checked_at': datetime.now(timezone.utc).isoformat(),
            'probe_kind': 'runtime_registration', 'generation_tested': False}
