"""Explicit fake external model responses; product translation code stays real."""
from dataclasses import replace
from app.contracts.providers import ProviderContract
from app.translation.ports import TranslationResponse
from app.translation.service import TranslationService

IDENTITY=ProviderContract(schema_version='1.0',provider_id='fake-glm',identity=dict(adapter='fake',model_id='fixture-glm',family='glm',connection_id='fake-glm'),identity_status='verified',identity_source='fixture:fake',connection_version='1')


class FakeTranslationPort:
    test_only=True
    identity=IDENTITY
    def __init__(self,phase,transform=None,findings=()):
        self.phase=phase; self.transform=transform; self.findings=findings; self.calls=[]; self.responses={}
    async def invoke(self,request):
        assert request.phase==self.phase
        self.calls.append(request)
        if self.phase=='translate':
            if self.transform: blocks=self.transform(request)
            else:
                if request.target_language=='en':
                    blocks={b['block_id']:b['source'].replace('保留原文件。','Keep the original file.').replace('禁止删除原始文件。','Do not delete original files.').replace('只增加 ','Only add ').replace('。','.') for b in request.blocks}
                else:
                    blocks={b['block_id']:b['source'].replace('Keep the original file. INTERNAL_ENGLISH_CANARY','保留原文件。').replace('Keep the original file.','保留原文件。') for b in request.blocks}
            response=TranslationResponse(blocks=blocks,identity=self.identity,usage={'total_tokens':10})
        else:
            findings=self.findings(request) if callable(self.findings) else self.findings
            response=TranslationResponse(findings=tuple(findings),identity=self.identity,usage={'total_tokens':3})
        self.responses[request.request_id]=response
        return response
    async def request_status(self,request_id): return 'completed' if request_id in self.responses else 'not_started'
    async def recover(self,request_id): return self.responses[request_id]


def service(client,transform=None,findings=(),**options):
    translator=FakeTranslationPort('translate',transform); checker=FakeTranslationPort('check',findings=findings)
    return TranslationService(client.app.state.database.path,translator,checker,**options)


def claude_turn(client,text='保留原文件。',conversation=None,key='one'):
    from contextlib import closing
    with closing(client.app.state.database.connect()) as connection:
        connection.execute("INSERT OR IGNORE INTO provider_profiles(id,adapter,model_id,family,connection_id,identity_status,identity_source,connection_version) VALUES ('fake-claude','fake','fixture-claude','claude','fake-claude','verified','fixture:fake','1')")
    conversation=conversation or client.post('/v1/conversations',json={'title':'translation fake'}).json()['id']
    accepted=client.post(f'/v1/conversations/{conversation}/turns',json={'text':text,'provider_profile_id':'fake-claude','client_request_id':key}).json()
    with closing(client.app.state.database.connect()) as connection:
        attempt=connection.execute('SELECT attempt_id FROM task_runs WHERE task_id=? ORDER BY attempt_number DESC',(accepted['task_id'],)).fetchone()[0]
    return conversation,accepted['task_id'],attempt
