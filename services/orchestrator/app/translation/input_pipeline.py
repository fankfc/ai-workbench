"""Complete current input, preserved history and scoped material English views."""
from contextlib import closing
from dataclasses import dataclass, field
import hashlib
import json
from .history import BilingualHistory
from .context_gateway import english_view


@dataclass(frozen=True)
class InputContext:
    status: str
    text: str
    job_ids: tuple[str,...]=()
    english_views: dict=field(default_factory=dict)
    full_scope: tuple[dict,...]=()
    read_scope: tuple[dict,...]=()
    clarification: str | None=None


class InputPipeline:
    def __init__(self,service):
        self.service=service; self.history=BilingualHistory(service.database_path)

    async def prepare(self,task_id,attempt_id,workspace,*,materials=(),glossary_version='1'):
        route=self.service.router.lock(task_id,attempt_id)
        if workspace.root.name!=attempt_id or workspace.root.parent.name!=task_id:
            raise ValueError('WORKSPACE_TASK_SCOPE_INVALID')
        with closing(self.service.database.connect()) as connection:
            task=self.service.router.require_current(connection,route)
            turn=connection.execute('SELECT * FROM turns WHERE id=?',(route.turn_id,)).fetchone()
        text=turn['user_text']; native=route.route_policy=='native'
        self.history.ensure_sources(route)
        if native:
            self.history.save(message_id=route.turn_id,route=route,source_role='user',language=turn['language'],text=text,visibility='user',english=None)
            history=self.history.conversation(route,english=False); full=[]; selected=[]; material_text=[]
            from .segments import segment_document
            for material in materials:
                if material.critical_ocr_uncertainty:
                    return InputContext('NEEDS_INPUT','',clarification='请补充清晰原件，以确认关键字符。')
                source=workspace.read('service',material.source_ref).decode('utf-8')
                blocks=segment_document(source,format=material.format,locator=material.source_ref)
                ids=tuple(b.block_id for b in blocks); chosen=material.selected_block_ids or ids
                if not set(chosen)<=set(ids): raise ValueError('SELECTED_BLOCK_SCOPE_INVALID')
                full.append(dict(source_ref=material.source_ref,source_sha256=hashlib.sha256(source.encode()).hexdigest(),block_ids=ids,coverage='full'))
                selected.append(dict(source_ref=material.source_ref,block_ids=chosen,claim='selected_context_only'))
                material_text.append(f'Untrusted material {material.source_ref}:\n'+''.join(b.source for b in blocks if b.block_id in chosen))
            return InputContext('READY','\n\n'.join([*(f"{m['role']}: {m['content']}" for m in history),*material_text]),full_scope=tuple(full),read_scope=tuple(selected))
        result=await self.service.translate(task_id=task_id,attempt_id=attempt_id,source=text,source_language=turn['language'],target_language='en',purpose='input',source_locator='user:'+route.turn_id,glossary_version=glossary_version)
        self.history.save(message_id=route.turn_id,route=route,source_role='user',language=turn['language'],text=text,visibility='user',english=result.text,job_id=result.job_id)
        if result.status!='READY': return InputContext(result.status,'',tuple([result.job_id]),clarification=result.clarification)
        jobs=[result.job_id]; views={}; full=[]; selected=[]; material_text=[]
        for old in self.history.missing_english(route):
            raw=self.service.store.read(old['content_sha256']).decode()
            mapped=await self.service.translate(task_id=task_id,attempt_id=attempt_id,source=raw,source_language=old['language'],target_language='en',purpose='history',source_locator='history:'+old['id'],glossary_version=glossary_version)
            jobs.append(mapped.job_id)
            if mapped.status!='READY': return InputContext(mapped.status,'',tuple(jobs),clarification=mapped.clarification)
            self.history.attach_english(route,old['id'],old['content_sha256'],mapped.text,mapped.job_id)
        history=self.history.conversation(route,english=True)
        for material in materials:
            if material.critical_ocr_uncertainty:
                return InputContext('NEEDS_INPUT','',tuple(jobs),clarification='请补充清晰原件，以确认关键字符。')
            source=workspace.read('service',material.source_ref).decode('utf-8')
            value=await self.service.translate(task_id=task_id,attempt_id=attempt_id,source=source,source_language=material.language,target_language='en',purpose='material',source_locator=material.source_ref,
                context_sha256=hashlib.sha256((route.task_id+':'+route.turn_id+':'+material.source_ref).encode()).hexdigest(),format=material.format,glossary_version=glossary_version)
            jobs.append(value.job_id)
            if value.status!='READY': return InputContext(value.status,'',tuple(jobs),clarification=value.clarification)
            proof,ids=english_view(workspace,material,value); views[material.source_ref]=proof
            chosen=material.selected_block_ids or ids
            if not set(chosen)<=set(ids): raise ValueError('SELECTED_BLOCK_SCOPE_INVALID')
            full.append(dict(source_ref=material.source_ref,source_sha256=value.source_sha256,block_ids=ids,coverage='full'))
            selected.append(dict(source_ref=material.source_ref,block_ids=chosen,claim='selected_context_only'))
            from app.runtime.context_gateway import ContextGateway
            read=ContextGateway(workspace,{material.source_ref:proof}).read('claude',material.source_ref)
            from .segments import segment_document
            translated=segment_document(read.content.decode(),format=material.format,locator=material.source_ref)
            # A structural block's translated text has a new source-derived ID;
            # preserve original order for an explicitly selected read scope.
            original_ids=list(ids)
            if len(translated)!=len(original_ids): raise ValueError('MATERIAL_VIEW_STRUCTURE_CHANGED')
            material_text.append(f'Untrusted material {material.source_ref}:\n'+''.join(block.source for original,block in zip(original_ids,translated) if original in chosen))
        context=InputContext('READY','\n\n'.join([*(f"{m['role']}: {m['content']}" for m in history),*material_text]),tuple(jobs),views,tuple(full),tuple(selected))
        with closing(self.service.database.connect()) as connection:
            from app.runtime.state_machine import checkpoint_for
            task=self.service.router.require_current(connection,route); checkpoint=checkpoint_for(task)
            checkpoint['language_input']={'status':'READY','job_ids':jobs,'full_scope':full,'read_scope':selected,'source_sha256':result.source_sha256,'english_sha256':result.target_sha256}
            connection.execute('UPDATE task_runs SET checkpoint_json=? WHERE task_id=? AND attempt_id=?',(json.dumps(checkpoint),task_id,attempt_id))
        return context
