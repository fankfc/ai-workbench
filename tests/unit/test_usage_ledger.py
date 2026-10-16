from contextlib import closing
import pytest
from app.usage.normalization import normalize_usage
from app.usage.ledger import UsageLedger
from app.usage.budgets import check_budget

@pytest.fixture
def ledger(client):
    conversation=client.post('/v1/conversations',json={'title':'usage'}).json()['id']
    task=client.post(f'/v1/conversations/{conversation}/turns',json={'text':'工作','provider_profile_id':'fake-gpt','client_request_id':'one'}).json()['task_id']
    with closing(client.app.state.database.connect()) as connection:
        attempt=connection.execute('SELECT attempt_id FROM task_runs WHERE task_id=?',(task,)).fetchone()[0]
    return UsageLedger(client.app.state.database.path),task,attempt

def record(ledger,task,attempt,**extra):
    args=dict(task_id=task,attempt_id=attempt,provider_profile_id='fake-gpt',external_request_id='req',event_id='event1',provider='gpt',raw={'total_tokens':120},source='reported',mode='request_total',sequence=1,role='B',function='execution',domain='code',status='completed')
    args.update(extra)
    return ledger.record(**args)

def test_duplicate_request_total_counted_once(ledger):
    book,task,attempt=ledger
    record(book,task,attempt)
    record(book,task,attempt)
    record(book,task,attempt,event_id='duplicate_bill',sequence=2)
    assert book.summary(task)['total_tokens']==120

def test_cumulative_120_to_200_and_late_lower(ledger):
    book,task,attempt=ledger
    record(book,task,attempt,mode='cumulative')
    record(book,task,attempt,mode='cumulative',raw={'total_tokens':200},sequence=2,event_id='event2')
    record(book,task,attempt,mode='cumulative',raw={'total_tokens':100},sequence=1,event_id='late')
    assert book.summary(task)['total_tokens']==200

def test_incremental_events_and_duplicates(ledger):
    book,task,attempt=ledger
    record(book,task,attempt,mode='delta',raw={'total_tokens':30})
    record(book,task,attempt,mode='delta',raw={'total_tokens':50},event_id='event2',sequence=2)
    record(book,task,attempt,mode='delta',raw={'total_tokens':50},event_id='event2',sequence=2)
    assert book.summary(task)['total_tokens']==80

def test_conflicting_duplicate_binding_or_event_rejected(ledger):
    book,task,attempt=ledger
    record(book,task,attempt)
    with pytest.raises(ValueError):
        record(book,task,attempt,role='A')
    with pytest.raises(ValueError):
        record(book,task,attempt,raw={'total_tokens':121})

def test_gpt_cache_reasoning_are_subsets_of_total():
    value=normalize_usage('gpt',{'input_tokens':100,'output_tokens':20,'input_tokens_details':{'cached_tokens':80},'output_tokens_details':{'reasoning_tokens':10}})
    assert value['total_tokens']==120

def test_claude_cache_mapping_is_explicit():
    value=normalize_usage('claude',{'input_tokens':20,'output_tokens':10,'cache_read_input_tokens':80,'cache_creation_input_tokens':5})
    assert value['total_tokens']==115

@pytest.mark.parametrize('provider,raw',[('gpt',{}),('gpt',{'input_tokens':10}),('unknown',{'total_tokens':99})])
def test_missing_unrecognized_is_unknown(provider,raw):
    value=normalize_usage(provider,raw)
    assert value['total_tokens'] is None and value['source']=='unknown'

@pytest.mark.parametrize('bad',[True,-1,1.5,'120',float('nan')])
def test_invalid_counts_rejected(bad):
    with pytest.raises(ValueError):
        normalize_usage('gpt',{'total_tokens':bad})

@pytest.mark.parametrize('status',['failed','cancelled','completed'])
def test_all_real_requests_remain_in_totals(ledger,status):
    book,task,attempt=ledger
    record(book,task,attempt,status=status)
    assert book.summary(task)['total_tokens']==120
    assert book.summary(task)['requests'][0]['status']==status

def test_unknown_not_zero_and_persists_after_reopen(ledger):
    book,task,attempt=ledger
    record(book,task,attempt,raw={})
    summary=UsageLedger(book.database_path).summary(task)
    assert summary['total_tokens'] is None and summary['unknown_requests']==1
    assert summary['tokens_per_delivery'] is None
    assert not check_budget(summary,total_tokens=1000,reserved_a_tokens=200,role='B',estimated_tokens=100)['allowed']

def test_reserve_a_and_stop_before_start():
    summary={'total_tokens':700,'known_lower_bound':700,'unknown_requests':0,'a_tokens':0}
    assert not check_budget(summary,total_tokens=1000,reserved_a_tokens=200,role='B',estimated_tokens=101)['allowed']
    assert check_budget(summary,total_tokens=1000,reserved_a_tokens=200,role='B',estimated_tokens=100)['allowed']
    assert check_budget(summary,total_tokens=1000,reserved_a_tokens=200,role='A',estimated_tokens=300)['allowed']
    assert not check_budget(summary,total_tokens=1000,reserved_a_tokens=200,role='A',estimated_tokens=301)['allowed']
    assert not check_budget(summary,total_tokens=1000,reserved_a_tokens=200,role='A',estimated_tokens=None)['allowed']

def test_translation_takeover_and_review_counted(ledger):
    book,task,attempt=ledger
    for index,(role,function) in enumerate([('B','execution'),('B','translation'),('A','review'),('A','takeover')]):
        record(book,task,attempt,external_request_id=f'req{index}',event_id=f'e{index}',role=role,function=function)
    summary=book.summary(task)
    assert summary['total_tokens']==480 and summary['a_tokens']==240
    assert summary['tokens_per_delivery'] is None
    assert {r['function'] for r in summary['requests']}=={'execution','translation','review','takeover'}

def test_session_cumulative_across_requests_uses_verified_difference(ledger):
    book,task,attempt=ledger
    record(book,task,attempt,mode='cumulative',cumulative_scope='session')
    record(book,task,attempt,mode='cumulative',cumulative_scope='session',external_request_id='req2',event_id='e2',sequence=2,raw={'total_tokens':200})
    summary=book.summary(task)
    assert summary['total_tokens']==200
    assert sorted(r['total_tokens'] for r in summary['requests'])==[80,120]

def test_estimate_is_distinct_and_reported_can_replace_it(ledger):
    book,task,attempt=ledger
    record(book,task,attempt,source='estimated',raw={'total_tokens':150})
    assert book.summary(task)['requests'][0]['source']=='estimated'
    record(book,task,attempt,source='reported',raw={'total_tokens':120},event_id='real',sequence=2)
    summary=book.summary(task)
    assert summary['total_tokens']==120
    assert summary['requests'][0]['source']=='reported'

def test_unknown_delta_cannot_be_hidden_by_later_known_delta(ledger):
    book,task,attempt=ledger
    record(book,task,attempt,mode='delta',raw={})
    record(book,task,attempt,mode='delta',raw={'total_tokens':50},event_id='known',sequence=2)
    summary=book.summary(task)
    assert summary['total_tokens'] is None and summary['known_lower_bound']==50

def test_untested_published_state_does_not_qualify_delivery(ledger,client):
    book,task,attempt=ledger
    with closing(client.app.state.database.connect()) as connection:
        connection.execute("UPDATE task_runs SET state='PUBLISHED' WHERE task_id=?",(task,))
    assert book.summary(task)['qualified_deliveries']==0

def test_delta_retransmit_with_new_event_id_is_still_one_sequence(ledger):
    book,task,attempt=ledger
    record(book,task,attempt,mode='delta',raw={'total_tokens':30})
    record(book,task,attempt,mode='delta',raw={'total_tokens':30},event_id='alias')
    assert book.summary(task)['total_tokens']==30
    with pytest.raises(ValueError):
        record(book,task,attempt,mode='delta',raw={'total_tokens':31},event_id='conflict')

@pytest.mark.parametrize('mode',['request_total','cumulative','delta'])
def test_unknown_start_reservation_resolves_to_observed_wire_mode(ledger,mode):
    book,task,attempt=ledger
    record(book,task,attempt,mode='pending',source='unknown',raw={'usage_observed':False,'request_start_confirmed':False},status='running')
    assert book.summary(task)['total_tokens'] is None
    record(book,task,attempt,mode=mode,event_id='observed',sequence=2,raw={'total_tokens':30})
    assert book.summary(task)['total_tokens']==30
    record(book,task,attempt,mode='pending',source='unknown',raw={'usage_observed':False,'request_start_confirmed':False},status='running')
    assert book.summary(task)['total_tokens']==30
