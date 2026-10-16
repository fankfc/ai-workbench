from contextlib import closing
from dataclasses import dataclass
import hashlib
import json
from app.storage.database import Database, transaction


@dataclass(frozen=True)
class GlossarySnapshot:
    domain: str | None
    entries: tuple[dict, ...]
    content_sha256: str


class GlossaryStore:
    def __init__(self,database_path): self.database=Database(database_path)
    def put(self,task_id,version,domain,entries,*,reason,affected_blocks=()):
        if not all(isinstance(value,str) and value.strip() for value in (task_id,version,domain,reason)):
            raise ValueError('GLOSSARY_VERSION_AND_REASON_REQUIRED')
        for item in entries:
            if set(item)!={'source','target','sense'} or not all(isinstance(v,str) and v for v in item.values()):
                raise ValueError('GLOSSARY_SENSE_REQUIRED')
        with closing(self.database.connect()) as connection,transaction(connection):
            connection.execute('INSERT INTO translation_glossaries VALUES (?,?,?,?,?,?)',(task_id,version,domain,json.dumps(entries),reason,json.dumps(list(affected_blocks))))
    def entries(self,task_id,version):
        return self.snapshot(task_id,version).entries

    def snapshot(self,task_id,version):
        with closing(self.database.connect()) as connection:
            row=connection.execute('SELECT domain,entries_json FROM translation_glossaries WHERE task_id=? AND version=?',(task_id,version)).fetchone()
        domain=row['domain'] if row else None
        entries=tuple(json.loads(row['entries_json'])) if row else ()
        content=json.dumps({'installed':row is not None,'domain':domain,'entries':entries},
            ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()
        return GlossarySnapshot(domain,entries,hashlib.sha256(content).hexdigest())
