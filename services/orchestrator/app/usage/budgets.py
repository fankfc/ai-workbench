"""Conservative pre-start gate; caller persists a checkpoint when denied."""
from .normalization import _count

def check_budget(summary,*,total_tokens,reserved_a_tokens,role,estimated_tokens):
    total=_count(total_tokens)
    reserve=_count(reserved_a_tokens)
    estimate=_count(estimated_tokens)
    if total is None or reserve is None or reserve>total or role not in ('A','B'):
        raise ValueError('INVALID_BUDGET_POLICY')
    if summary.get('unknown_requests') or summary.get('total_tokens') is None:
        return {'allowed':False,'reason':'UNKNOWN_USAGE','remaining_tokens':None}
    if estimate is None:
        return {'allowed':False,'reason':'ESTIMATE_REQUIRED','remaining_tokens':None}
    spent=_count(summary['total_tokens'])
    a_spent=_count(summary.get('a_tokens',0))
    remaining=total-spent-(max(reserve-a_spent,0) if role=='B' else 0)
    return {'allowed':estimate<=remaining,'reason':'OK' if estimate<=remaining else 'BUDGET_EXHAUSTED','remaining_tokens':max(remaining,0)}
