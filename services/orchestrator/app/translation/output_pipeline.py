"""Retain A's internal English answer and translate its complete immutable bytes."""
from contextlib import closing
import json
from app.storage.blobs import read_artifact
from .history import BilingualHistory


class OutputPipeline:
    def __init__(self,service): self.service=service; self.history=BilingualHistory(service.database_path)
    async def prepare(self,task_id,attempt_id,source_revision_id,*,complete=True,explicit_retry=False,purpose='output'):
        route=self.service.router.lock(task_id,attempt_id)
        with closing(self.service.database.connect()) as connection:
            self.service.router.require_current(connection,route)
            artifact=connection.execute('SELECT * FROM artifact_revisions WHERE id=? AND task_id=? AND attempt_id=?',(source_revision_id,task_id,attempt_id)).fetchone()
            if artifact is None: raise ValueError('OUTPUT_SOURCE_SCOPE_INVALID')
            text=read_artifact(connection,self.service.store,source_revision_id).decode()
            if route.route_policy=='claude_en_bridge':
                if (not complete or artifact['language']!='en' or artifact['canonical_issued_by']!='A'
                        or 'A' not in json.loads(artifact['origin_authors_json'])):
                    raise ValueError('COMPLETE_A_ENGLISH_OUTPUT_REQUIRED')
                from app.documents.canonical import require_canonical
                require_canonical(connection,self.service.store,source_revision_id)
                self.history.save(message_id=source_revision_id,route=route,source_role='assistant',language='en',text=text,visibility='internal')
        return await self.service.translate(task_id=task_id,attempt_id=attempt_id,source=text,source_language='en',target_language='zh-CN',purpose=purpose,
            source_ref=artifact['immutable_uri'],source_version_id=source_revision_id,source_locator='artifact:'+source_revision_id,explicit_retry=explicit_retry)
