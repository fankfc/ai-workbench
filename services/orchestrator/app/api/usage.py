"""Read-only paged accounting. Never export raw provider observations."""
from contextlib import closing
from datetime import datetime
import json
from typing import Literal
from fastapi import APIRouter, HTTPException, Query, Request
from app.usage.ledger import UsageLedger

router = APIRouter()

COMPONENTS = ('input_tokens', 'output_tokens', 'cached_tokens', 'reasoning_tokens',
              'cache_read_input_tokens', 'cache_creation_input_tokens')


def component_view(details):
    """Expose normalized counts without ever returning the provider wire body.

    Session cumulative totals do not provide request-level component deltas;
    those components remain unavailable rather than being copied to each request.
    """
    empty = dict(components={key: None for key in COMPONENTS}, mapping_version=None,
                 component_semantics='unknown')
    events = [event for event in details.get('events', [])
              if event.get('mode') != 'pending' and not event.get('ignored_duplicate_sequence')]
    if not events or details.get('total_tokens') is None or details.get('binding', {}).get('cumulative_scope'):
        return empty
    if details['binding']['mode'] == 'delta':
        selected = events
        normalized = selected[-1]['normalized']
        components = {key: sum(event['normalized']['components'][key] for event in selected)
            if all(type(event['normalized'].get('components', {}).get(key)) is int for event in selected) else None
            for key in COMPONENTS}
    else:
        selected = [event for event in events if event['normalized'].get('total_tokens') == details['total_tokens']
                    and event['normalized'].get('source') == details['source']]
        if not selected:
            return empty
        normalized = max(selected, key=lambda event: event['sequence'])['normalized']
        components = {key: normalized.get('components', {}).get(key) for key in COMPONENTS}
    semantics = 'cache_is_additional_input' if 'cache_read_input_tokens' in normalized.get('components', {}) else 'cache_is_input_subset'
    return dict(components=components, mapping_version=normalized.get('mapping_version'), component_semantics=semantics)


def usage_view(request, *, role=None, function=None, task_id=None, date_from=None, date_to=None, offset=0, limit=50):
    where = ["metric='request'"]
    args = []
    if task_id is not None:
        where.append('task_id=?')
        args.append(task_id)
    boundaries = []
    for operator, value in [('>=', date_from), ('<=', date_to)]:
        if value is None:
            continue
        try:
            parsed = datetime.fromisoformat(value.replace('Z','+00:00'))
            if parsed.tzinfo is None or 'T' not in value:
                raise ValueError('timezone required')
        except (ValueError, AttributeError):
            raise HTTPException(422,'日期范围需要包含时间和时区。') from None
        boundaries.append(parsed)
        # Compare instants, including offset timestamps and fractional seconds.
        where.append('julianday(created_at) '+operator+' julianday(?)')
        args.append(parsed.isoformat())
    if len(boundaries)==2 and boundaries[0]>boundaries[1]:
        raise HTTPException(422,'开始日期不能晚于结束日期。')
    items = []
    with closing(request.app.state.database.connect()) as connection:
        rows = connection.execute('SELECT * FROM usage_entries WHERE ' + ' AND '.join(where) + ' ORDER BY created_at DESC,id', args).fetchall()
        for row in rows:
            details = json.loads(row['details_json'])
            binding = details.get('binding', {})
            if (role is not None and binding.get('role') != role) or (function is not None and binding.get('function') != function):
                continue
            items.append(dict(id=row['id'], task_id=row['task_id'], role=binding.get('role'),
                function=binding.get('function'), domain=binding.get('domain'), status=details.get('status'),
                provider_profile_id=row['provider_profile_id'], external_request_id=row['external_request_id'],
                source=details.get('source', 'unknown'), total_tokens=details.get('total_tokens'),
                known_lower_bound=details.get('known_lower_bound', 0), created_at=row['created_at'],
                **component_view(details)))
    with closing(request.app.state.database.connect()) as connection:
        task_ids = [row[0] for row in connection.execute('SELECT DISTINCT task_id FROM task_runs')]
    qualified_all = sum(UsageLedger(request.app.state.database.path).summary(identity)['qualified_deliveries'] for identity in task_ids)
    unknown = sum(item['total_tokens'] is None for item in items)
    a_items = [item for item in items if item['role'] == 'A']
    a_unknown = any(item['total_tokens'] is None for item in a_items)
    a_total = None if a_unknown else sum(item['total_tokens'] for item in a_items)
    # Qualified denominator is global; scoped reports must not imply comparable deliveries.
    scoped = any(value is not None for value in (role, function, task_id, date_from, date_to))
    qualified = None if scoped else qualified_all
    summary = dict(total_tokens=None if unknown else sum(item['total_tokens'] for item in items),
        known_lower_bound=sum(item['known_lower_bound'] for item in items), unknown_requests=unknown,
        a_tokens=a_total, qualified_deliveries=qualified,
        tokens_per_delivery=a_total / qualified if qualified and a_total is not None else None,
        savings=None, benchmark_status='not_evaluated', scope='filtered' if scoped else 'all_requests')
    return dict(items=items[offset:offset + limit], next_offset=offset + limit if len(items) > offset + limit else None, summary=summary)


@router.get('/v1/usage')
def get_usage(request: Request, role: Literal['A', 'B'] | None = None,
              function: Literal['execution', 'translation', 'review', 'planning', 'takeover'] | None = None,
              task_id: str | None = None, date_from: str | None = None, date_to: str | None = None,
              offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100)):
    return usage_view(request, role=role, function=function, task_id=task_id, date_from=date_from, date_to=date_to, offset=offset, limit=limit)
