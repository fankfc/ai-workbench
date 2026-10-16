"""Allowlisted local diagnostics, never a dump of state or exception payloads."""
from contextlib import closing
import io
import json
import platform
import zipfile
from fastapi import APIRouter, Request
from fastapi.responses import Response
from .settings import connection_views
from .usage import usage_view

router = APIRouter()


@router.post('/v1/diagnostics/export')
def export_diagnostics(request: Request):
    with closing(request.app.state.database.connect()) as connection:
        profiles = connection_views(request, connection)
        states = {row[0]: row[1] for row in connection.execute('SELECT state,COUNT(*) FROM task_runs GROUP BY state')}
    # Reapply allowlist: public model IDs may be operator-entered and are omitted here.
    profiles = [{key: item[key] for key in ('role', 'family', 'identity_status', 'available', 'provider_mode')} for item in profiles]
    usage = usage_view(request, limit=100)
    usage['items'] = [{key: item[key] for key in ('role', 'function', 'status', 'source', 'total_tokens', 'known_lower_bound')} for item in usage['items']]
    payload = dict(protocol_version='1.0', python_version=platform.python_version(),
                   provider_mode=request.app.state.settings.provider_mode,
                   connections=profiles, task_state_counts=states, usage=usage,
                   raw_materials_included=False)
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('diagnostics.json', json.dumps(payload, ensure_ascii=False, indent=2))
    return Response(stream.getvalue(), media_type='application/zip', headers={'Content-Disposition': 'attachment; filename="workbench-diagnostics.zip"', 'Cache-Control': 'no-store'})
