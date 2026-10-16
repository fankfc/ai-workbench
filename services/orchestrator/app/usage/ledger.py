"""Durable request totals backed by D008 usage_entries; raw observations retained."""
import hashlib
import json
from contextlib import closing
from pathlib import Path
from uuid import uuid4

from app.storage.database import Database,transaction
from .normalization import normalize_usage,_count

class UsageLedger:
    def __init__(self,database_path):
        self.database_path=Path(database_path)
        self.database=Database(self.database_path)

    def record(self,*,task_id,attempt_id,provider_profile_id,external_request_id,event_id,provider,raw,source,mode,sequence,role,function,domain,status,cumulative_scope=None):
        if role not in ('A','B') or function not in ('execution','translation','review','planning','takeover') or domain not in ('code','paper','document','mixed') or status not in ('running','completed','failed','cancelled') or mode not in ('pending','request_total','cumulative','delta'):
            raise ValueError('INVALID_USAGE_CONTEXT')
        if type(sequence) is not int or sequence<1 or not all(isinstance(v,str) and v.strip() for v in (task_id,attempt_id,provider_profile_id,external_request_id,event_id)):
            raise ValueError('INVALID_USAGE_BINDING')
        normalized=normalize_usage(provider,raw,source)
        if mode=='pending' and (source!='unknown' or raw.get('usage_observed') is not False or cumulative_scope is not None):
            raise ValueError('PENDING_IS_UNOBSERVED_RESERVATION_ONLY')
        snapshot={'event_id':event_id,'sequence':sequence,'raw':raw,'normalized':normalized,'mode':mode,'status':status,'cumulative_scope':cumulative_scope}
        fingerprint=hashlib.sha256(json.dumps(snapshot,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
        snapshot['sha256']=fingerprint
        binding={'task_id':task_id,'attempt_id':attempt_id,'provider_profile_id':provider_profile_id,'external_request_id':external_request_id,'provider':provider,'role':role,'function':function,'domain':domain,'mode':mode,'cumulative_scope':cumulative_scope}
        with closing(self.database.connect()) as connection,transaction(connection):
            task=connection.execute('SELECT 1 FROM task_runs WHERE task_id=? AND attempt_id=?',(task_id,attempt_id)).fetchone()
            if task is None:
                raise ValueError('UNKNOWN_USAGE_TASK')
            old=connection.execute("SELECT * FROM usage_entries WHERE provider_profile_id=? AND external_request_id=? AND metric='request'",(provider_profile_id,external_request_id)).fetchone()
            if old:
                detail=json.loads(old['details_json'])
                ignored={'mode','cumulative_scope'}
                if any(detail['binding'].get(key)!=value for key,value in binding.items() if key not in ignored):
                    raise ValueError('USAGE_REQUEST_BINDING_MISMATCH')
                duplicate=next((e for e in detail['events'] if e['event_id']==event_id),None)
                if duplicate:
                    if duplicate['sha256']!=fingerprint:
                        raise ValueError('USAGE_EVENT_CONFLICT')
                    return detail
                if detail['binding']!=binding:
                    if detail['binding']['mode']=='pending' and mode!='pending' and all(e['mode']=='pending' for e in detail['events']):
                        detail['binding']=binding
                    else:
                        raise ValueError('USAGE_REQUEST_BINDING_MISMATCH')
                if mode=='delta':
                    prior_sequence=next((e for e in detail['events'] if e['sequence']==sequence),None)
                    if prior_sequence is not None:
                        fields=('raw','normalized','mode','status','cumulative_scope')
                        if any(prior_sequence.get(key)!=snapshot.get(key) for key in fields):
                            raise ValueError('USAGE_SEQUENCE_CONFLICT')
                        detail['events'].append({**snapshot,'ignored_duplicate_sequence':True})
                        connection.execute('UPDATE usage_entries SET details_json=? WHERE id=?',(json.dumps(detail,sort_keys=True,separators=(',',':'),allow_nan=False),old['id']))
                        return detail
            else:
                detail={'binding':binding,'events':[],'total_tokens':None,'source':'unknown','high_sequence':0,'status':status,'known_lower_bound':0}
            count=normalized['total_tokens']
            high=detail['high_sequence']
            if cumulative_scope is not None:
                if mode!='cumulative' or not isinstance(cumulative_scope,str) or not cumulative_scope:
                    raise ValueError('INVALID_CUMULATIVE_SCOPE')
                previous=[]
                for row in connection.execute("SELECT details_json FROM usage_entries WHERE provider_profile_id=? AND metric='request'",(provider_profile_id,)):
                    candidate=json.loads(row[0])
                    if candidate['binding'].get('cumulative_scope')==cumulative_scope:
                        previous.extend(e for e in candidate['events'] if e['normalized']['total_tokens'] is not None)
                newest=max(previous,key=lambda e:e['sequence'],default=None)
                if newest and sequence<=newest['sequence']:
                    if sequence==newest['sequence'] and count!=newest['normalized']['total_tokens']:
                        raise ValueError('CUMULATIVE_SEQUENCE_CONFLICT')
                    count=0
                elif count is not None:
                    prior=newest['normalized']['total_tokens'] if newest else 0
                    if count<prior:
                        raise ValueError('CUMULATIVE_COUNTER_DECREASED')
                    count-=prior
                # A scoped session counter allocates its verified difference to this request.
                detail['total_tokens']=None if count is None else (detail['total_tokens'] or 0)+count
                detail['known_lower_bound']+=count or 0
                detail['source']=normalized['source']
            elif mode=='delta':
                detail['known_lower_bound']+=count or 0
                prior_unknown=any(e['mode']!='pending' and e['normalized']['total_tokens'] is None for e in detail['events'])
                detail['total_tokens']=None if count is None or prior_unknown else detail['known_lower_bound']
                detail['source']='unknown' if detail['total_tokens'] is None else ('estimated' if source=='estimated' or detail['source']=='estimated' else 'reported')
            elif sequence>=high:
                prior=detail['total_tokens']
                if count is not None:
                    if prior is not None and count<prior and source==detail['source']:
                        raise ValueError('REQUEST_COUNTER_DECREASED')
                    if source=='reported' or detail['source']!='reported':
                        detail['total_tokens']=count
                        detail['source']=normalized['source']
                        detail['known_lower_bound']=count
            detail['events'].append(snapshot)
            detail['high_sequence']=max(high,sequence)
            if detail['status']=='running':
                detail['status']=status
            payload=json.dumps(detail,sort_keys=True,separators=(',',':'),allow_nan=False)
            if old:
                connection.execute('UPDATE usage_entries SET details_json=? WHERE id=?',(payload,old['id']))
            else:
                # Quantity=1 counts the request. Unknown tokens are null in details, never synthetic zero.
                connection.execute("INSERT INTO usage_entries(id,task_id,attempt_id,provider_profile_id,external_request_id,metric,quantity,unit,details_json) VALUES (?,?,?,?,?,'request',1,'request',?)",(uuid4().hex,task_id,attempt_id,provider_profile_id,external_request_id,payload))
            return detail

    def summary(self,task_id):
        with closing(self.database.connect()) as connection:
            details=[json.loads(row[0]) for row in connection.execute("SELECT details_json FROM usage_entries WHERE task_id=? AND metric='request' ORDER BY created_at,id",(task_id,))]
            from app.runtime.public_projection import _release_payload
            from app.storage.blobs import BlobStore
            deliveries=0
            for row in connection.execute("SELECT * FROM task_runs WHERE task_id=? AND state='PUBLISHED' AND cancel_requested=0",(task_id,)):
                try:
                    if _release_payload(connection,BlobStore(self.database_path.parent/'blobs'),row,'answer.published') is not None:
                        deliveries+=1
                except (ValueError,OSError,KeyError,TypeError):
                    pass
        unknown=sum(item['total_tokens'] is None for item in details)
        lower=sum(item['known_lower_bound'] for item in details)
        total=None if unknown else sum(item['total_tokens'] for item in details)
        requests=[{**item['binding'],'status':item['status'],'source':item['source'],'total_tokens':item['total_tokens'],'events':item['events']} for item in details]
        return {'total_tokens':total,'known_lower_bound':lower,'unknown_requests':unknown,'a_tokens':sum(item['known_lower_bound'] for item in details if item['binding']['role']=='A'),'qualified_deliveries':deliveries,'tokens_per_delivery':total/deliveries if deliveries and total is not None else None,'requests':requests}
