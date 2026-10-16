"""Durable state/public event delivery."""
from pathlib import Path
from contextlib import closing
import json
import uuid

from app.contracts.events import PublicEvent
from app.storage.database import Database, transaction


class OutboxError(ValueError):
    pass


def enqueue_event(connection, task_id, attempt_id, kind, payload, *, deduplication_key, public_payload=None, event_id=None):
    if not connection.in_transaction:
        raise OutboxError("OUTBOX_TRANSACTION_REQUIRED")
    if not isinstance(payload, dict) or not isinstance(deduplication_key, str) or not deduplication_key.strip():
        raise OutboxError("OUTBOX_PAYLOAD_OR_KEY_INVALID")
    encoded = _json(payload)
    existing = connection.execute("SELECT * FROM outbox_events WHERE deduplication_key=?", (deduplication_key,)).fetchone()
    if existing is not None:
        public = json.loads(existing["public_event_json"]) if existing["public_event_json"] is not None else None
        if (existing["task_id"] != task_id or existing["attempt_id"] != attempt_id or existing["kind"] != kind
                or json.loads(existing["internal_payload_json"]) != payload
                or (public["payload"] if public is not None else None) != public_payload
                or (event_id is not None and existing["event_id"] != event_id)):
            raise OutboxError("DEDUPLICATION_KEY_CONFLICT")
        return dict(existing)
    row = connection.execute("""SELECT r.*,t.conversation_id FROM task_runs r JOIN turns t ON r.turn_id=t.id
                              WHERE r.task_id=? AND r.attempt_id=?""", (task_id, attempt_id)).fetchone()
    if row is None:
        raise OutboxError("OUTBOX_ATTEMPT_NOT_FOUND")
    sequence = max(row["last_sequence"], connection.execute(
        "SELECT coalesce(max(sequence),0) FROM outbox_events WHERE task_id=? AND attempt_id=?", (task_id,attempt_id)
    ).fetchone()[0]) + 1
    conversation_sequence = connection.execute(
        "SELECT coalesce(max(conversation_sequence),0)+1 FROM outbox_events WHERE conversation_id=?", (row["conversation_id"],)
    ).fetchone()[0]
    event_id = event_id or uuid.uuid4().hex
    public_json = None
    if public_payload is not None:
        public = PublicEvent.model_validate(dict(schema_version="1.0", event_id=event_id,
            conversation_id=row["conversation_id"], turn_id=row["turn_id"], task_id=task_id,
            attempt_id=attempt_id, sequence=conversation_sequence, kind=kind, payload=public_payload))
        public_json = public.model_dump_json()
    connection.execute("""INSERT INTO outbox_events(event_id,conversation_id,turn_id,task_id,attempt_id,
        sequence,conversation_sequence,kind,contract_version,internal_payload_json,public_event_json,deduplication_key)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""", (event_id,row["conversation_id"],row["turn_id"],task_id,attempt_id,
        sequence,conversation_sequence,kind,row["contract_version"],encoded,public_json,deduplication_key))
    connection.execute("UPDATE task_runs SET last_sequence=? WHERE task_id=? AND attempt_id=?", (sequence,task_id,attempt_id))
    return dict(connection.execute("SELECT * FROM outbox_events WHERE event_id=?", (event_id,)).fetchone())


class Outbox:
    def __init__(self, database_path: Path):
        self.database_path = Path(database_path)

    def pending(self):
        with closing(Database(self.database_path).connect()) as connection:
            return [dict(row) for row in connection.execute(
                "SELECT * FROM outbox_events WHERE delivery_state='PENDING' ORDER BY created_at,conversation_id,conversation_sequence"
            )]

    def dispatch(self, send, limit=100):
        if type(limit) is not int or limit < 1:
            raise OutboxError("INVALID_DISPATCH_LIMIT")
        sent = 0
        for row in self.pending()[:limit]:
            with closing(Database(self.database_path).connect()) as connection:
                with transaction(connection):
                    connection.execute("UPDATE outbox_events SET delivery_attempts=delivery_attempts+1 WHERE event_id=? AND delivery_state='PENDING'",
                                       (row["event_id"],))
                public = self._project(connection, row)
            if public is not None:
                send(public)
                sent += 1
            self.acknowledge(row["event_id"])
        return sent

    def replay(self, conversation_id, after_seq=0):
        if type(after_seq) is not int or after_seq < 0:
            raise OutboxError("INVALID_REPLAY_CURSOR")
        with closing(Database(self.database_path).connect()) as connection:
            rows = connection.execute("""SELECT * FROM outbox_events WHERE conversation_id=?
                AND conversation_sequence>? ORDER BY conversation_sequence""", (conversation_id,after_seq)).fetchall()
            return [public for row in rows if (public := self._project(connection, row)) is not None]

    def _project(self, connection, row):
        # A valid PublicEvent declaration is not release authority. Reuse the
        # exact server-owned gate used for API history/SSE for every transport.
        from .public_projection import ProjectionContext, project_event
        from app.storage.blobs import BlobStore
        value = dict(task_id=row["task_id"],attempt_id=row["attempt_id"],sequence=row["sequence"],kind=row["kind"],
                     payload=json.loads(row["internal_payload_json"]))
        return project_event(value,context=ProjectionContext(connection,row["event_id"],BlobStore(self.database_path.parent/"blobs")))

    def acknowledge(self, event_id):
        with closing(Database(self.database_path).connect()) as connection:
            with transaction(connection):
                cursor = connection.execute("""UPDATE outbox_events SET delivery_state='DELIVERED',
                    delivered_at=coalesce(delivered_at,strftime('%Y-%m-%dT%H:%M:%fZ','now')) WHERE event_id=?""", (event_id,))
                if cursor.rowcount != 1:
                    raise OutboxError("OUTBOX_EVENT_NOT_FOUND")


def _json(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
