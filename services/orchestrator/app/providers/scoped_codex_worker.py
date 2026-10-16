"""Stdlib private worker: pinned CLI pipes, sealed RPC, bounded SSE projection.

The parent owns the kill-on-close Job. Non-breakaway children inherit it.
Only control scalars, owned references and original final text cross the pipe;
config, authentication, raw log records and reasoning stay in private memory.
"""
from contextlib import suppress
import hashlib
import json
import os
from pathlib import Path
import queue
import re
import subprocess
import sys
import threading
import time

ENTRY_SHA256 = '4b01d5920e6785614727443bbecf343f4dedbb7347052b72ba805aab6353ef01'
ENTRY_SUFFIX = '/OpenAI/Codex/bin/f544b3844e0f14e9/codex.exe'
ROUTE = 'workbench_scoped_chatgpt_http'
ROUTE_VALUE = '{name="Workbench scoped ChatGPT HTTP",base_url="https://chatgpt.com/backend-api/codex",wire_api="responses",requires_openai_auth=true,supports_websockets=false,request_max_retries=0,stream_max_retries=0}'
CONTROLS = {
    'features.shell_tool': False, 'features.view_image': False,
    'features.code_mode': False, 'features.code_mode_only': False,
    'features.code_mode_host.enabled': False, 'features.code_mode_host.disable_in_process_fallback': False,
    'features.multi_agent': False, 'features.multi_agent_v2': False, 'features.apps': False,
    'features.plugins': False, 'features.tool_suggest': False, 'features.recommended_plugins': False,
    'features.memories': False, 'memories.use_memories': False,
    'cloud.skills.enabled': False, 'features.image_generation': False, 'web_search': 'disabled',
    'features.hooks': False, 'notify': [], 'features.deferred_executor': False,
    'features.request_permissions_tool': False, 'agents.enabled': False,
}
METHODS = frozenset({'initialize', 'initialized', 'config/read', 'thread/start', 'thread/read',
                     'thread/unsubscribe', 'turn/start', 'turn/interrupt'})
POLICY = {'version': '2', 'controls': CONTROLS, 'methods': sorted(METHODS),
    'thread': {'ephemeral': True, 'environments': [], 'dynamicTools': [], 'approvalPolicy': 'never',
               'sandbox': 'read-only', 'allowProviderModelFallback': False},
    'turn': {'environments': [], 'approvalPolicy': 'never', 'sandboxPolicy': {'type': 'readOnly', 'networkAccess': False}},
    'route': ROUTE, 'route_value': ROUTE_VALUE, 'source_tag': 'rust-v0.160.0'}
POLICY_SHA256 = hashlib.sha256(json.dumps(POLICY, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


class WorkerError(RuntimeError): pass


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result: raise WorkerError('DUPLICATE_JSON_FIELD')
        result[key] = value
    return result


def parse(data):
    return json.loads(data, object_pairs_hook=unique_object,
        parse_constant=lambda _: (_ for _ in ()).throw(WorkerError('INVALID_JSON_NUMBER')))


def safe_id(value):
    return value if isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9_.:/-]{1,180}', value) and not value.lower().startswith(('sk-', 'bearer', 'eyj')) else None


def exact(a, b):
    if type(a) is not type(b): return False
    if isinstance(b, dict): return set(a) == set(b) and all(exact(a[k], v) for k, v in b.items())
    if isinstance(b, list): return len(a) == len(b) and all(exact(x, y) for x, y in zip(a, b))
    return a == b


def control_projection(config):
    if not isinstance(config, dict): raise WorkerError('EFFECTIVE_CONFIG_INVALID')
    projected, valid = {}, True
    for path, expected in CONTROLS.items():
        node = config
        for key in path.split('.'):
            node = node.get(key) if isinstance(node, dict) else None
        valid = valid and exact(node, expected)
        projected[path] = node if exact(node, expected) else None
    servers = config.get('mcp_servers')
    if not isinstance(servers, dict) or any(not isinstance(k, str) or len(k) > 256 or '\0' in k for k in servers):
        raise WorkerError('MCP_EFFECTIVE_KEYS_UNAVAILABLE')
    safe = {'controls': projected, 'mcp_servers': {k: {'enabled': v.get('enabled') if isinstance(v, dict) and type(v.get('enabled')) is bool else None} for k, v in servers.items()},
        'configured_provider_id': safe_id(config.get('model_provider')), 'configured_model_id': safe_id(config.get('model'))}
    return safe, valid


def thread_projection(result, *, require_route=False):
    thread = result.get('thread') if isinstance(result, dict) else None
    if not isinstance(thread, dict) or not safe_id(thread.get('id')): raise WorkerError('OWNED_THREAD_UNBOUND')
    projected={'thread': {'id': thread['id'], 'ephemeral': thread.get('ephemeral') is True,
                       'environments': [] if thread.get('environments') == [] else None,
                       'turns': [] if thread.get('turns') == [] else None}}
    if 'approvalPolicy' in result: projected['approvalPolicy']='never' if result['approvalPolicy']=='never' else None
    if 'sandbox' in result: projected['sandbox']={'type':'readOnly','networkAccess':False} if exact(result['sandbox'],{'type':'readOnly','networkAccess':False}) else None
    for field in ('model','modelProvider'):
        if field in result: projected[field]=safe_id(result[field])
    if require_route and any(projected.get(field) is None for field in ('model','modelProvider')):
        raise WorkerError('THREAD_CONFIGURED_ROUTE_MISSING')
    return projected


class SseProjection:
    """Configured models and request echoes never grant execution identity."""
    def __init__(self):
        self.response_ids, self.models = set(), set()
        self.completed, self.created_id = None, None
        self.complete_count = 0
        self.invalid = False

    def feed(self, line):
        try: self._feed(line)
        except WorkerError:
            self.invalid=True
            raise

    def _feed(self, line):
        try: record = parse(line)
        except (ValueError, UnicodeError, TypeError): return
        if not isinstance(record, dict) or record.get('target') != 'codex_api::sse::responses' or record.get('level') != 'TRACE': return
        fields = record.get('fields')
        message = fields.get('message') if isinstance(fields, dict) else None
        if not isinstance(message, str) or not message.startswith('SSE event: '): return
        try: event = parse(message[11:])
        except (ValueError, TypeError): raise WorkerError('SSE_INVALID_SERVER_EVENT') from None
        if not isinstance(event, dict): raise WorkerError('SSE_INVALID_SERVER_EVENT')
        if event.get('type') not in {'response.created', 'response.completed', 'response.incomplete'}: return
        response = event.get('response')
        if not isinstance(response, dict): raise WorkerError('SSE_RESPONSE_FIELDS_MISSING')
        ident = safe_id(response.get('id'))
        if not ident or not ident.startswith('resp_'): raise WorkerError('SSE_RESPONSE_FIELDS_MISSING')
        self.response_ids.add(ident)
        values = {safe_id(response[k]) for k in ('model','modelId','model_id') if response.get(k) is not None}
        if None in values or len(values)>1: raise WorkerError('SSE_MODEL_FIELDS_CONFLICT')
        self.models.update(values)
        if len(self.response_ids)>1 or len(self.models)>1: raise WorkerError('SSE_COMPLETION_NOT_UNIQUE')
        if event['type']=='response.created': self.created_id=ident
        elif event['type']=='response.incomplete': raise WorkerError('SSE_RESPONSE_INCOMPLETE')
        else:
            self.complete_count += 1
            if self.complete_count!=1: raise WorkerError('SSE_COMPLETION_NOT_UNIQUE')
            model=safe_id(response.get('model'))
            if response.get('status')!='completed' or response.get('object','response')!='response' or not model:
                raise WorkerError('SSE_COMPLETED_MODEL_MISSING')
            self.completed={'response_id':ident,'actual_model_id':model}


class PipePeer:
    def __init__(self, command, cwd, deadline, limit, authority, stage):
        self.command,self.cwd,self.deadline,self.limit=command,cwd,deadline,limit
        self.authority,self.stage=authority,stage
        self.frames=queue.Queue(maxsize=256)
        self.process=None
        self.counter=self.seen_bytes=0
        self.limit_lock=threading.Lock()
        self.replies={}
        self.notifications=None
        self.sse=SseProjection()
        self.readers=[]

    def start(self):
        environment={k:v for k,v in os.environ.items() if k in {'SYSTEMROOT','WINDIR','PATH','PATHEXT','NUMBER_OF_PROCESSORS','PROCESSOR_ARCHITECTURE','TEMP','TMP'}}
        environment.update(RUST_LOG='off,codex_api::sse::responses=trace',LOG_FORMAT='json')
        self.process=subprocess.Popen(self.command,cwd=self.cwd,stdin=subprocess.PIPE,stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,shell=False,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0),env=environment)
        for label,stream in [('stdout',self.process.stdout),('stderr',self.process.stderr)]:
            reader=threading.Thread(target=self._read,args=(label,stream),daemon=True)
            self.readers.append(reader); reader.start()

    def _read(self,label,stream):
        pending=b''
        try:
            while True:
                data=os.read(stream.fileno(),4096)
                if not data: break
                with self.limit_lock:
                    self.seen_bytes+=len(data); too_large=self.seen_bytes>self.limit
                if too_large: self.frames.put(('error','OUTPUT_LIMIT')); return
                pending+=data
                while b'\n' in pending:
                    line,pending=pending.split(b'\n',1)
                    if line.strip(): self.frames.put((label,line))
            if pending: self.frames.put(('error','TRUNCATED_PROVIDER_FRAME') if label=='stdout' else (label,pending))
        except OSError: pass
        finally: self.frames.put(('eof',label))

    def write(self,frame):
        data=json.dumps(frame,ensure_ascii=True,allow_nan=False).encode()+b'\n'
        if len(data)>self.limit: raise WorkerError('INPUT_LIMIT')
        self.process.stdin.write(data); self.process.stdin.flush()

    def send(self,method,params,notify=False):
        if method not in METHODS: raise WorkerError('RPC_METHOD_FORBIDDEN')
        self.authority(method,params,self.stage)
        self.counter+=1
        frame={'method':method,'params':params}
        if not notify: frame['id']=self.counter
        self.write(frame); return self.counter

    def pump(self,wait=.01):
        if time.monotonic()>=self.deadline: raise WorkerError('TIMEOUT')
        if os.environ.get('AI_RUNTIME_CANCEL_FILE') and Path(os.environ['AI_RUNTIME_CANCEL_FILE']).exists(): raise WorkerError('CANCELLED')
        try: label,data=self.frames.get(timeout=wait)
        except queue.Empty: return
        if label=='error': raise WorkerError(data)
        if label=='eof':
            if data=='stdout': raise WorkerError('PROVIDER_DISCONNECTED')
            return
        if label=='stderr': self.sse.feed(data); return
        try: frame=parse(data)
        except (ValueError,UnicodeError,TypeError): raise WorkerError('INVALID_PROVIDER_FRAME') from None
        if not isinstance(frame,dict): raise WorkerError('INVALID_PROVIDER_FRAME')
        method=frame.get('method')
        if method is not None:
            if 'id' in frame:
                self.write({'id':frame['id'],'error':{'code':-32601,'message':'Unsupported private runtime client request'}})
                raise WorkerError('UNSUPPORTED_SERVER_CALLBACK')
            if self.notifications: self.notifications(method,frame.get('params',{}))
        elif type(frame.get('id')) is int:
            if frame['id'] in self.replies or frame['id']>self.counter: raise WorkerError('UNEXPECTED_RPC_RESPONSE')
            self.replies[frame['id']]=frame
        else: raise WorkerError('INVALID_PROVIDER_FRAME')

    def call(self,method,params):
        ident=self.send(method,params)
        while ident not in self.replies: self.pump()
        frame=self.replies.pop(ident)
        if 'error' in frame: raise WorkerError('PROVIDER_RPC_ERROR')
        return frame.get('result')

    def close(self):
        if self.process is None: return
        with suppress(OSError): self.process.stdin.close()
        try: self.process.wait(timeout=.25)
        except subprocess.TimeoutExpired:
            with suppress(OSError): self.process.terminate()
            with suppress(subprocess.TimeoutExpired): self.process.wait(timeout=.5)
        for reader in self.readers: reader.join(timeout=.3)
        for stream in (self.process.stdout,self.process.stderr):
            with suppress(OSError): stream.close()


class Worker:
    def __init__(self,boot):
        self.boot=boot
        self.deadline=time.monotonic()+boot['timeout_seconds']
        self.limit=boot['max_output_bytes']
        self.peer=None
        self.thread_id=self.turn_id=self.started_id=None
        self.accepted=self.submitted=self.started_sent=self.completed=False
        self.final_text=None
        self.receipts=[]
        self.raw_receipt_count=0
        self.control_verified=False
        self.written_bytes=0
        self.stage=None

    def emit(self,kind,**values):
        data=json.dumps(dict(kind=kind,nonce=self.boot['nonce'],**values),ensure_ascii=True,allow_nan=False).encode()+b'\n'
        self.written_bytes+=len(data)
        if self.written_bytes>self.limit: raise WorkerError('OUTPUT_LIMIT')
        sys.stdout.buffer.write(data); sys.stdout.buffer.flush()

    def authorize(self,method,params,stage):
        safe_params=params
        if method=='turn/start':
            if self.boot['action']!='invoke' or self.submitted or not self.control_verified: raise WorkerError('MODEL_PRECONDITIONS_MISSING')
            if params.get('threadId')!=self.thread_id or params.get('environments')!=[] or params.get('approvalPolicy')!='never' or not exact(params.get('sandboxPolicy'),{'type':'readOnly','networkAccess':False}):
                raise WorkerError('TURN_SCOPE_INVALID')
            safe_params=dict(params); safe_params.pop('input')
            safe_params['input_source_sha256']=self.boot['input_source_sha256']
        self.emit('rpc.authorize',method=method,params=safe_params,stage=stage,thread_id=self.thread_id,turn_id=self.turn_id)
        reply=sys.stdin.buffer.readline(self.limit+1)
        if len(reply)>self.limit: raise WorkerError('AUTHORIZATION_LIMIT')
        try: permission=parse(reply)
        except (ValueError,UnicodeError): raise WorkerError('AUTHORIZATION_INVALID') from None
        if not exact(permission,{'nonce':self.boot['nonce'],'allow':True}): raise WorkerError('RPC_AUTHORIZATION_DENIED')
        if method=='turn/start': self.submitted=True; self.emit('submitted',submitted_model_turns=1)

    def observed(self,method,result,stage):
        self.emit('rpc.observed',method=method,result=result,stage=stage)
        # Keep the issued process live until its verifier has consumed this
        # response. A fast final unsubscribe must not race verifier cleanup.
        reply=sys.stdin.buffer.readline(self.limit+1)
        try: observed=parse(reply)
        except (ValueError,UnicodeError): raise WorkerError('OBSERVATION_ACK_INVALID') from None
        if len(reply)>self.limit or not exact(observed,{'nonce':self.boot['nonce'],'observed':True}):
            raise WorkerError('OBSERVATION_ACK_INVALID')

    def entry_check(self):
        if self.boot['transport_kind']=='fixture': return
        exe=Path(self.boot['executable']).resolve(strict=True)
        if not str(exe).replace('\\','/').endswith(ENTRY_SUFFIX) or hashlib.sha256(exe.read_bytes()).hexdigest()!=ENTRY_SHA256:
            raise WorkerError('OFFICIAL_ENTRY_PIN_MISMATCH')

    def command(self,restricted,keys):
        if self.boot['transport_kind']=='fixture': return list(self.boot['fixture_command'])
        command=[self.boot['executable']]
        if restricted:
            for key,value in CONTROLS.items(): command.extend(['-c',key+'='+json.dumps(value,ensure_ascii=True)])
            inline='{'+','.join(json.dumps(key,ensure_ascii=True)+'={enabled=false}' for key in keys)+'}'
            command.extend(['-c','mcp_servers='+inline,'-c','model='+json.dumps(self.boot['expected_model']),
                '-c','model_provider='+json.dumps(ROUTE),'-c','model_providers.'+ROUTE+'='+ROUTE_VALUE])
        return command+['app-server','--listen','stdio://']

    def initialize(self,restricted,keys):
        self.stage='restricted' if restricted else 'baseline'
        self.peer=PipePeer(self.command(restricted,keys),self.boot['workspace'],self.deadline,self.limit,self.authorize,self.stage)
        self.peer.notifications=self.notification; self.peer.start()
        self.peer.call('initialize',{'clientInfo':{'name':'workbench_scoped_runtime','title':'Scoped native runtime','version':'0.1.0'},'capabilities':{'experimentalApi':True}})
        self.observed('initialize',{},self.stage)
        self.peer.send('initialized',{},notify=True)

    def config(self):
        raw=self.peer.call('config/read',{'cwd':self.boot['workspace'],'includeLayers':False})
        projection,valid=control_projection(raw.get('config') if isinstance(raw,dict) else None)
        self.observed('config/read',projection,self.stage)
        return projection,valid

    def prepare(self):
        self.entry_check(); self.initialize(False,[])
        baseline,_=self.config(); keys=set(baseline['mcp_servers'])
        self.peer.close(); self.peer=None
        self.initialize(True,keys)
        restricted,valid=self.config()
        if not valid: raise WorkerError('REQUIRED_SCOPE_CONTROL_UNVERIFIED')
        if set(restricted['mcp_servers'])!=keys or any(v['enabled'] is not False for v in restricted['mcp_servers'].values()): raise WorkerError('MCP_RESTRICTION_NOT_VERIFIED')
        params=dict(POLICY['thread'],cwd=self.boot['workspace'],experimentalRawEvents=True,model=self.boot['expected_model'],modelProvider=ROUTE)
        start=thread_projection(self.peer.call('thread/start',params),require_route=self.boot['transport_kind']=='native'); self.thread_id=start['thread']['id']
        self.observed('thread/start',start,self.stage)
        if not (start['thread']['ephemeral'] and start['thread']['environments']==[] and start['approvalPolicy']=='never' and exact(start['sandbox'],{'type':'readOnly','networkAccess':False})):
            raise WorkerError('STRICT_THREAD_POLICY_UNVERIFIED')
        read=thread_projection(self.peer.call('thread/read',{'threadId':self.thread_id,'includeTurns':False}))
        self.observed('thread/read',read,self.stage)
        if read['thread']['id']!=self.thread_id or read['thread']['ephemeral'] is not True or read['thread']['environments']!=[]: raise WorkerError('STICKY_EMPTY_ENVIRONMENT_UNVERIFIED')
        self.control_verified=True
        self.emit('prepared',controls_verified=True,control_count=len(CONTROLS),policy_sha256=POLICY_SHA256,mcp_keys_match=True,
            all_mcp_disabled=True,configured_mcp_count=len(keys),thread_id=self.thread_id,thread_start_verified=True,thread_read_verified=True,transport_kind=self.boot['transport_kind'])
        return keys

    def maybe_started(self):
        if self.started_sent or not self.turn_id or not self.peer.sse.created_id: return
        self.started_id=self.peer.sse.created_id; self.started_sent=True
        self.emit('started',external_request_id=self.started_id,external_execution_id=self.turn_id)

    def notification(self,method,params):
        if not isinstance(method,str) or not isinstance(params,dict): raise WorkerError('INVALID_NOTIFICATION')
        if method in {'thread/started','thread/status/changed','mcpServer/startupStatus/updated','warning'}:
            if params.get('threadId') is not None and params['threadId']!=self.thread_id: raise WorkerError('FOREIGN_THREAD_EVENT')
            return
        if not self.submitted: raise WorkerError('UNEXPECTED_PREPARATION_ACTIVITY')
        if method=='rawResponse/completed': self.raw_receipt_count+=1
        thread=params.get('threadId') or params.get('thread_id')
        turn=params.get('turnId') or params.get('turn_id')
        if method in {'turn/started','turn/completed'}: turn=params.get('turn',{}).get('id') if isinstance(params.get('turn'),dict) else None
        if thread!=self.thread_id or turn!=self.turn_id: raise WorkerError('FOREIGN_EXECUTION_EVENT')
        if method=='turn/started': return
        if method=='turn/completed':
            if self.completed or params['turn'].get('status')!='completed' or params['turn'].get('error') is not None: raise WorkerError('TURN_NOT_COMPLETED')
            self.completed=True; return
        if method=='rawResponse/completed':
            rid=safe_id(params.get('responseId')); usage=params.get('usage')
            if not rid or not isinstance(usage,dict): raise WorkerError('USAGE_RECEIPT_MISSING')
            projected={}
            for camel,snake in [('inputTokens','input_tokens'),('outputTokens','output_tokens'),('totalTokens','total_tokens'),('cachedInputTokens','cached_input_tokens'),('reasoningOutputTokens','reasoning_output_tokens')]:
                value=usage.get(camel,usage.get(snake))
                if value is not None:
                    if type(value) is not int or value<0: raise WorkerError('USAGE_RECEIPT_INVALID')
                    projected[snake]=value
            if not {'input_tokens','output_tokens'}<=set(projected): raise WorkerError('USAGE_RECEIPT_MISSING')
            total=projected['input_tokens']+projected['output_tokens']
            if projected.get('total_tokens',total)!=total or projected.get('reasoning_output_tokens',0)>projected['output_tokens']: raise WorkerError('USAGE_RECEIPT_INVALID')
            projected['total_tokens']=total
            self.receipts.append({'response_id':rid,'thread_id':thread,'turn_id':turn,'usage':projected})
            if len(self.receipts)!=1: raise WorkerError('RAW_RECEIPT_NOT_UNIQUE')
            return
        if method in {'item/completed','item/started'}:
            item=params.get('item')
            if not isinstance(item,dict) or item.get('type') not in {'agentMessage','reasoning','plan'}: raise WorkerError('TOOL_ACTIVITY_FORBIDDEN')
            if method=='item/completed' and item['type']=='agentMessage':
                text=item.get('text')
                if not isinstance(text,str) or not text.strip() or self.final_text is not None: raise WorkerError('FINAL_TEXT_NOT_UNIQUE')
                self.final_text=text
            return
        if method in {'item/agentMessage/delta','item/reasoning/summaryTextDelta','item/reasoning/textDelta','item/reasoning/summaryPartAdded','turn/plan/updated','thread/tokenUsage/updated','rawResponse/itemCompleted'}: return
        raise WorkerError('UNSUPPORTED_EXECUTION_NOTIFICATION')

    def bound_usage(self):
        """Return only actual, unique response evidence bound to the started turn."""
        if not (self.submitted and self.accepted and self.started_sent and self.peer is not None
                and safe_id(self.thread_id) and safe_id(self.turn_id) and safe_id(self.started_id)):
            return None
        sse=self.peer.sse
        if (sse.invalid or sse.complete_count!=1 or sse.response_ids!={self.started_id}
                or sse.models!={self.boot['expected_model']} or sse.created_id!=self.started_id
                or not sse.completed or self.raw_receipt_count!=1 or len(self.receipts)!=1):
            return None
        identity,receipt=sse.completed,self.receipts[0]
        if (identity['response_id']!=self.started_id or identity['actual_model_id']!=self.boot['expected_model']
                or (receipt['response_id'],receipt['thread_id'],receipt['turn_id'])
                    !=(self.started_id,self.thread_id,self.turn_id)):
            return None
        return dict(external_request_id=self.started_id,external_execution_id=self.turn_id,
            actual_model_id=identity['actual_model_id'],identity_source='official_response_completed_model',
            thread_id=self.thread_id,usage=receipt['usage'])

    def failed_usage(self):
        # Finish the local readers before checking uniqueness. A queued later
        # completion or raw receipt must not hide behind the protocol error.
        if self.peer is None: return None
        self.peer.close()
        if any(reader.is_alive() for reader in self.peer.readers): return None
        trusted=True
        while not self.peer.frames.empty():
            label,data=self.peer.frames.get()
            if label=='stderr':
                try: self.peer.sse.feed(data)
                except (WorkerError,ValueError,UnicodeError,TypeError): trusted=False
            elif label=='error': trusted=False
            elif label=='stdout':
                try: frame=parse(data)
                except (WorkerError,ValueError,UnicodeError,TypeError):
                    trusted=False; continue
                if isinstance(frame,dict) and frame.get('method')=='rawResponse/completed':
                    try: self.notification(frame['method'],frame.get('params',{}))
                    except (WorkerError,ValueError,TypeError): trusted=False
        if not trusted: return None
        # The stderr reader may deliver response.created only after stdout's
        # fatal event. Bind the single started reference after both pipes drain,
        # before an unknown-reference fallback can freeze it for the parent.
        self.maybe_started()
        return self.bound_usage()

    def invoke(self,keys):
        self.entry_check(); current,valid=self.config()
        if not valid or set(current['mcp_servers'])!=keys or any(v['enabled'] is not False for v in current['mcp_servers'].values()): raise WorkerError('SCOPE_CHANGED_BEFORE_START')
        read=thread_projection(self.peer.call('thread/read',{'threadId':self.thread_id,'includeTurns':False})); self.observed('thread/read',read,self.stage)
        if read['thread']['id']!=self.thread_id or read['thread']['environments']!=[] or read['thread']['ephemeral'] is not True: raise WorkerError('SCOPE_CHANGED_BEFORE_START')
        text=self.boot['text']
        if hashlib.sha256(text.encode()).hexdigest()!=self.boot['input_source_sha256']: raise WorkerError('INPUT_SOURCE_CHANGED')
        params=dict(POLICY['turn'],threadId=self.thread_id,cwd=self.boot['workspace'],model=self.boot['expected_model'],effort='low',input=[{'type':'text','text':text,'text_elements':[]}],outputSchema=self.boot['output_schema'])
        result=self.peer.call('turn/start',params); self.accepted=True
        turn=result.get('turn') if isinstance(result,dict) else None
        self.turn_id=safe_id(turn.get('id')) if isinstance(turn,dict) else None
        self.emit('accepted',external_execution_id=self.turn_id)
        self.observed('turn/start',{'turn':{'id':self.turn_id,'status':turn.get('status') if isinstance(turn,dict) else None}},self.stage)
        if not self.turn_id: raise WorkerError('UNKNOWN_REMOTE')
        while not (self.completed and self.final_text is not None and self.peer.sse.completed and len(self.receipts)==1): self.peer.pump(); self.maybe_started()
        self.maybe_started()
        identity=self.peer.sse.completed; receipt=self.receipts[0]
        if not self.started_sent or identity['response_id']!=self.started_id or receipt['response_id']!=self.started_id or identity['actual_model_id']!=self.boot['expected_model']:
            raise WorkerError('ACTUAL_MODEL_IDENTITY_MISMATCH')
        self.peer.call('thread/unsubscribe',{'threadId':self.thread_id})
        self.observed('thread/unsubscribe',{},self.stage)
        self.peer.close()
        while not self.peer.frames.empty():
            label,data=self.peer.frames.get()
            if label=='stdout' and data.strip():
                # Keep a trailing receipt visible to the failure-only usage
                # verifier even though every trailing stdout frame is invalid.
                try: frame=parse(data)
                except (WorkerError,ValueError,UnicodeError,TypeError): frame=None
                if isinstance(frame,dict) and frame.get('method')=='rawResponse/completed':
                    self.raw_receipt_count+=1
                raise WorkerError('TRAILING_PROVIDER_ACTIVITY')
            if label=='error': raise WorkerError(data)
            if label=='stderr': self.peer.sse.feed(data)
        if self.peer.sse.complete_count!=1 or len(self.peer.sse.response_ids)!=1: raise WorkerError('SSE_COMPLETION_NOT_UNIQUE')
        self.emit('capture',external_request_id=self.started_id,external_execution_id=self.turn_id,actual_model_id=identity['actual_model_id'],
            identity_source='official_response_completed_model',final_text=self.final_text,final_sha256=hashlib.sha256(self.final_text.encode()).hexdigest(),usage=receipt['usage'],thread_id=self.thread_id,finished=True)

    def run(self):
        try:
            keys=self.prepare()
            if self.boot['action']=='invoke': self.invoke(keys)
            else:
                self.peer.call('thread/unsubscribe',{'threadId':self.thread_id})
                self.observed('thread/unsubscribe',{},self.stage)
        except Exception as error:
            if self.turn_id and self.peer is not None:
                with suppress(Exception):
                    self.peer.deadline=min(self.peer.deadline,time.monotonic()+.25)
                    self.peer.call('turn/interrupt',{'threadId':self.thread_id,'turnId':self.turn_id})
                    self.observed('turn/interrupt',{},self.stage)
                    self.emit('interrupt_ack',acknowledged=True,remote_state='unknown')
            evidence=None
            with suppress(Exception): evidence=self.failed_usage()
            if self.accepted and not self.started_sent:
                self.started_sent=True; self.emit('started',external_request_id=None,external_execution_id=self.turn_id)
            if evidence is not None:
                with suppress(Exception): self.emit('usage',**evidence)
            reason=str(error)
            if not re.fullmatch(r'[A-Z_]{1,90}',reason): reason='PRIVATE_WORKER_FAILED'
            if self.accepted and reason=='PROVIDER_DISCONNECTED': reason='UNKNOWN_REMOTE'
            with suppress(Exception): self.emit('error',reason_code=reason,remote_state='unknown',accepted=self.accepted)
            return 1
        finally:
            if self.peer: self.peer.close()
        return 0


def main():
    try:
        data=sys.stdin.buffer.readline(2_000_001)
        if len(data)>2_000_000: return 1
        boot=parse(data)
        if not isinstance(boot,dict) or boot.get('action') not in {'prepare','invoke'} or boot.get('transport_kind') not in {'native','fixture'}: return 1
        if not safe_id(boot.get('nonce')) or not safe_id(boot.get('expected_model')): return 1
        if type(boot.get('max_output_bytes')) is not int or not 1024<=boot['max_output_bytes']<=2_000_000: return 1
        if type(boot.get('timeout_seconds')) not in (int,float) or not 0<boot['timeout_seconds']<=120: return 1
        return Worker(boot).run()
    except Exception: return 1


if __name__=='__main__': raise SystemExit(main())
