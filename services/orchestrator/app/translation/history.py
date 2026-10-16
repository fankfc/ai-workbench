"""Full original/English mappings, constrained to the current conversation."""
from contextlib import closing
import hashlib
import json
from app.storage.database import Database, transaction
from app.storage.blobs import BlobStore


class BilingualHistory:
    def __init__(self,database_path):
        self.database=Database(database_path); self.store=BlobStore(self.database.path.parent/'blobs')

    def save(self,*,message_id,route,source_role,language,text,visibility,english=None,job_id=None,parent_message_id=None):
        raw=self.store.put(text.encode()); en=self.store.put(english.encode()) if english is not None else None
        with closing(self.database.connect()) as connection,transaction(connection):
            turn=connection.execute('SELECT * FROM turns WHERE id=? AND task_id=?',(route.turn_id,route.task_id)).fetchone()
            if not turn: raise ValueError('MESSAGE_TASK_SCOPE_INVALID')
            existing=connection.execute('SELECT * FROM bilingual_history WHERE id=?',(message_id,)).fetchone()
            if existing:
                if existing['content_sha256']!=raw.sha256 or existing['route_snapshot_id']!=route.id:
                    raise ValueError('MESSAGE_IDENTITY_CONFLICT')
                if en:
                    connection.execute('UPDATE bilingual_history SET english_ref=?,english_sha256=?,job_id=? WHERE id=?',
                        (self.store.uri_for(en.sha256),en.sha256,job_id,message_id))
                return
            connection.execute('INSERT INTO bilingual_history(id,conversation_id,task_id,turn_id,source_role,language,raw_content_ref,content_sha256,parent_message_id,route_snapshot_id,visibility,english_ref,english_sha256,job_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                (message_id,turn['conversation_id'],route.task_id,route.turn_id,source_role,language,self.store.uri_for(raw.sha256),raw.sha256,parent_message_id,route.id,visibility,
                 self.store.uri_for(en.sha256) if en else None,en.sha256 if en else None,job_id))

    def conversation(self,route,*,english):
        with closing(self.database.connect()) as connection:
            turn=connection.execute('SELECT * FROM turns WHERE id=?',(route.turn_id,)).fetchone()
            rows=connection.execute("SELECT h.* FROM bilingual_history h JOIN turns t ON t.id=h.turn_id WHERE h.conversation_id=? AND t.created_at<=? ORDER BY t.created_at,CASE WHEN h.source_role='user' THEN 0 ELSE 1 END,h.created_at,h.id",(turn['conversation_id'],turn['created_at'])).fetchall()
            result=[]
            for row in rows:
                # Internal English originals are represented once via the
                # approved translated message; do not duplicate answer history.
                if row['visibility']=='internal': continue
                source=self.store.read(row['content_sha256']).decode()
                if english:
                    if row['english_sha256'] is None: raise ValueError('HISTORY_ENGLISH_VIEW_REQUIRED')
                    if row['job_id']:
                        job=connection.execute('SELECT status FROM translation_jobs WHERE id=?',(row['job_id'],)).fetchone()
                        if job is None or job[0]!='READY':
                            if not self._published_mapping(connection,row): raise ValueError('HISTORY_TRANSLATION_NOT_READY')
                    content=self.store.read(row['english_sha256']).decode()
                else: content=source
                result.append(dict(message_id=row['id'],role=row['source_role'],content=content,source_sha256=row['content_sha256'],turn_id=row['turn_id']))
            return tuple(result)

    def missing_english(self,route):
        with closing(self.database.connect()) as connection:
            turn=connection.execute('SELECT conversation_id,created_at FROM turns WHERE id=?',(route.turn_id,)).fetchone()
            rows=connection.execute("SELECT h.* FROM bilingual_history h JOIN turns t ON t.id=h.turn_id LEFT JOIN translation_jobs j ON j.id=h.job_id WHERE h.conversation_id=? AND t.created_at<=? AND h.visibility!='internal' AND (h.english_sha256 IS NULL OR (h.source_role='user' AND j.status!='READY')) ORDER BY t.created_at,h.created_at",(turn['conversation_id'],turn['created_at'])).fetchall()
            return tuple(dict(row) for row in rows)

    def _published_mapping(self,connection,row):
        if row['source_role']=='assistant':
            clarification=connection.execute("SELECT details_json FROM checks WHERE task_id=? AND attempt_id=(SELECT attempt_id FROM translation_jobs WHERE id=?) AND check_kind='clarification.publication' AND result='pass' AND json_extract(details_json,'$.job_id')=?",(row['task_id'],row['job_id'],row['job_id'])).fetchone()
            if clarification:
                try:
                    from .clarification import validate_publication
                    detail=json.loads(clarification[0]); validate_publication(connection,self.store,detail['event_id'],historical=True)
                    return detail['release_id']==row['id'] and detail['target_sha256']==row['content_sha256'] and detail['source']['source_sha256']==row['english_sha256']
                except (ValueError,KeyError,TypeError): return False
        publication=connection.execute("SELECT details_json FROM checks WHERE task_id=? AND check_kind='release.publication' AND result='pass' AND json_extract(details_json,'$.translation_job_id')=?",(row['task_id'],row['job_id'])).fetchone()
        if row['source_role']!='assistant' or publication is None: return False
        details=json.loads(publication[0]); task=connection.execute('SELECT * FROM task_runs WHERE task_id=? AND attempt_id=?',(details['task_id'],details['attempt_id'])).fetchone()
        try:
            from app.runtime.answer_publication import validate_translation_release
            validate_translation_release(connection,self.store,task,dict(revision_id=details['artifact_version_id'],source_revision_id=details['source_revision_id'],translation_job_id=details['translation_job_id'],qa_id=details['qa_id'],sha256=details['artifact_sha256']),historical=True)
            return True
        except (ValueError,KeyError,TypeError): return False

    def ensure_sources(self,route):
        """Backfill original turns and actual approved answers from trusted storage."""
        from app.contracts.providers import RouteSnapshot
        from .router import persist_snapshot
        with closing(self.database.connect()) as connection:
            current=connection.execute('SELECT * FROM turns WHERE id=?',(route.turn_id,)).fetchone()
            turns=connection.execute('SELECT * FROM turns WHERE conversation_id=? AND created_at<=? ORDER BY created_at,id',(current['conversation_id'],current['created_at'])).fetchall()
            for turn in turns:
                data=json.loads(turn['route_snapshot_json']); data.pop('test_only',None)
                snapshot=RouteSnapshot.model_validate(data)
                with transaction(connection): persist_snapshot(connection,snapshot)
                self.save(message_id=turn['id'],route=snapshot,source_role='user',language=turn['language'],text=turn['user_text'],visibility='user')
            from app.runtime.public_projection import ProjectionContext,project_event
            events=connection.execute("SELECT e.* FROM outbox_events e JOIN turns t ON t.id=e.turn_id WHERE e.conversation_id=? AND t.created_at<=? AND e.kind='answer.published' ORDER BY e.conversation_sequence",(current['conversation_id'],current['created_at'])).fetchall()
            for event in events:
                public=project_event(dict(task_id=event['task_id'],attempt_id=event['attempt_id'],sequence=event['sequence'],kind=event['kind'],payload=json.loads(event['internal_payload_json'])),context=ProjectionContext(connection,event['event_id'],self.store))
                if public is None: continue
                payload=public['payload']; old_route=connection.execute('SELECT snapshot_json FROM route_snapshots WHERE task_id=? AND attempt_id=?',(event['task_id'],event['attempt_id'])).fetchone()
                if old_route:
                    self.save(message_id=payload['message_id'],route=RouteSnapshot.model_validate_json(old_route[0]),source_role='assistant',language=payload['language'],text=payload['text'],visibility='user')

    def attach_english(self,route,message_id,source_sha256,english,job_id):
        en=self.store.put(english.encode())
        with closing(self.database.connect()) as connection,transaction(connection):
            conversation=connection.execute('SELECT conversation_id FROM turns WHERE id=?',(route.turn_id,)).fetchone()[0]
            row=connection.execute('SELECT * FROM bilingual_history WHERE id=? AND conversation_id=?',(message_id,conversation)).fetchone()
            if row is None or row['content_sha256']!=source_sha256: raise ValueError('HISTORY_MAPPING_SCOPE_INVALID')
            connection.execute('UPDATE bilingual_history SET english_ref=?,english_sha256=?,job_id=? WHERE id=?',
                (self.store.uri_for(en.sha256),en.sha256,job_id,message_id))
